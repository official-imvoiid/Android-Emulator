"""Downloading, verifying and installing SDK packages.

Pure Python — no Java, no cmdline-tools, no sdkmanager. Everything sdkmanager does
for these packages is: resolve the URL from a manifest, download it, check the
hash, unzip it into a path derived from the package ID. We already read the
manifest, so doing it directly removes a ~150 MB tool plus a JDK dependency.
"""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import zipfile
from pathlib import Path

import httpx

from .. import settings
from ..events import bus
from . import installed
from .manifest import Archive, Package

CHUNK = 1024 * 256


class DownloadError(RuntimeError):
    pass


class _ResumeUnsupported(RuntimeError):
    """Raised when a partial file cannot be continued and must be restarted."""


async def _stream_to_file(
    client: httpx.AsyncClient,
    archive: Archive,
    target: Path,
    resume_from: int,
    *,
    label: str,
    job_id: str,
) -> None:
    """Stream the archive to disk, appending when resuming.

    Two details matter here:

    * `Accept-Encoding: identity`. These archives are already compressed, so
      transport compression buys nothing — and it actively breaks resuming,
      because a byte range taken from the middle of a gzip stream has no valid
      header and zlib rejects it ("incorrect header check"). Asking for identity
      keeps byte offsets, Content-Length and the checksum all in agreement.

    * `aiter_raw()` rather than `aiter_bytes()`. Raw bytes are what we want on
      disk; `aiter_bytes()` would apply content decoding, so what we counted and
      what we wrote could diverge from the manifest's size and hash.
    """
    headers = {"Accept-Encoding": "identity"}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
    mode = "ab" if resume_from else "wb"

    bus.publish("progress", jobId=job_id, label=label, stage="downloading",
                percent=(resume_from / archive.size * 100.0) if archive.size else 0.0,
                downloaded=resume_from, total=archive.size)

    try:
        async with client.stream("GET", archive.url, headers=headers, timeout=None,
                                 follow_redirects=True) as resp:
            if resp.status_code == 416:
                # Range not satisfiable: we already hold at least the whole file.
                return
            if resp.status_code not in (200, 206):
                raise DownloadError(f"HTTP {resp.status_code} downloading {archive.url}")

            if resume_from and resp.status_code == 200:
                # Range was ignored, so the body is the whole file from byte 0.
                # Appending it to what we have would corrupt the result.
                raise _ResumeUnsupported("server ignored the range request")

            # If the server compressed the body anyway, offsets and hash cannot
            # be trusted; restart without a range so httpx handles it as one
            # complete stream.
            if resp.headers.get("content-encoding", "identity").lower() not in ("identity", ""):
                if resume_from:
                    raise _ResumeUnsupported("server applied transport compression")

            done = resume_from
            remaining = int(resp.headers.get("content-length", 0) or 0)
            total = archive.size or (remaining + resume_from)
            last_emit = -1.0

            with target.open(mode) as fh:
                async for chunk in resp.aiter_raw(CHUNK):
                    fh.write(chunk)
                    done += len(chunk)
                    pct = (done / total * 100.0) if total else 0.0
                    # Throttle: a 2 GB download would otherwise emit ~8000 events.
                    if pct - last_emit >= 0.5 or (total and done >= total):
                        last_emit = pct
                        bus.publish("progress", jobId=job_id, label=label,
                                    stage="downloading", percent=round(pct, 1),
                                    downloaded=done, total=total)
    except httpx.DecodingError as exc:
        # Should not happen now that we ask for identity, but if a proxy forces
        # encoding anyway, recover instead of dying.
        if resume_from:
            raise _ResumeUnsupported(f"response could not be decoded: {exc}") from exc
        raise DownloadError(f"Could not decode the response for {label}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"Network error downloading {label}: {exc}") from exc

    if archive.size and target.exists() and target.stat().st_size != archive.size:
        actual = target.stat().st_size
        if resume_from:
            raise _ResumeUnsupported(
                f"ended at {actual} bytes but the manifest says {archive.size}"
            )
        raise DownloadError(
            f"{label} downloaded {actual} bytes but the manifest says {archive.size}. "
            "The download was incomplete; try again."
        )


def _staging_path(archive: Archive) -> Path:
    name = archive.url.rsplit("/", 1)[-1]
    return settings.DOWNLOAD_DIR / name


def _hash_file(path: Path, algo: str) -> str:
    try:
        digest = hashlib.new(algo)
    except ValueError:
        digest = hashlib.sha1()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest().lower()


async def download_archive(
    client: httpx.AsyncClient,
    archive: Archive,
    *,
    label: str,
    job_id: str,
) -> Path:
    """Download with resume, then verify the manifest checksum."""
    settings.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = _staging_path(archive)

    # An already-complete, verified file means a re-run costs nothing.
    if target.exists() and archive.size and target.stat().st_size == archive.size:
        if await asyncio.to_thread(_hash_file, target, archive.checksum_type) == archive.checksum.lower():
            bus.publish("progress", jobId=job_id, label=label, stage="verified",
                        percent=100.0, downloaded=archive.size, total=archive.size)
            return target

    resume_from = target.stat().st_size if target.exists() else 0
    if archive.size and resume_from > archive.size:
        resume_from = 0  # corrupt leftover; start clean
        target.unlink(missing_ok=True)

    try:
        await _stream_to_file(client, archive, target, resume_from, label=label, job_id=job_id)
    except _ResumeUnsupported as exc:
        # The partial file could not be continued (see _stream_to_file). Throw it
        # away and take the whole thing again rather than leaving a file that
        # would only fail its checksum at the very end.
        bus.log(f"Resuming failed ({exc}); restarting the download from the beginning.", "warn")
        target.unlink(missing_ok=True)
        await _stream_to_file(client, archive, target, 0, label=label, job_id=job_id)

    bus.publish("progress", jobId=job_id, label=label, stage="verifying", percent=100.0,
                downloaded=archive.size, total=archive.size)

    actual = await asyncio.to_thread(_hash_file, target, archive.checksum_type)
    if archive.checksum and actual != archive.checksum.lower():
        target.unlink(missing_ok=True)
        raise DownloadError(
            f"Checksum mismatch for {label} ({archive.checksum_type}). "
            "The download was discarded; try again."
        )
    return target


def _extract_sync(zip_path: Path, dest: Path, job_id: str, label: str) -> None:
    """Extract into `dest`, flattening the archive's single top-level folder.

    Package paths map onto directories, and the zip already supplies the leaf:
      emulator-windows_x64-*.zip  -> "emulator/"  -> <sdk>/emulator
      x86_64-36_r07.zip           -> "x86_64/"    -> <sdk>/system-images/.../x86_64
    So when there is exactly one top-level directory we move its *contents* into
    dest. Otherwise the archive is already flat and we move everything.
    """
    staging = dest.parent / f".staging-{dest.name}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        total = len(members) or 1
        for index, member in enumerate(members, start=1):
            zf.extract(member, staging)
            if index % 200 == 0 or index == total:
                bus.publish("progress", jobId=job_id, label=label, stage="extracting",
                            percent=round(index / total * 100.0, 1),
                            downloaded=index, total=total)

    top = [p for p in staging.iterdir()]
    source = top[0] if len(top) == 1 and top[0].is_dir() else staging

    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    shutil.rmtree(staging, ignore_errors=True)


async def install_package(
    client: httpx.AsyncClient,
    package: Package,
    *,
    job_id: str,
    keep_archive: bool = False,
) -> None:
    """Download + verify + extract one package, then record it as installed."""
    archive = package.archive_for_host()
    if archive is None:
        raise DownloadError(f"No download available for {package.path} on this platform.")

    label = f"{package.display_name} ({package.path})"
    bus.log(f"Installing {package.path} rev {package.revision_str}")

    zip_path = await download_archive(client, archive, label=label, job_id=job_id)
    dest = package.install_dir(settings.SDK_ROOT)

    await asyncio.to_thread(_extract_sync, zip_path, dest, job_id, label)

    installed.record(package.path, package.revision_str, archive.checksum, archive.size)
    bus.publish("progress", jobId=job_id, label=label, stage="done", percent=100.0,
                downloaded=archive.size, total=archive.size)
    bus.log(f"Installed {package.path}")

    if not keep_archive:
        zip_path.unlink(missing_ok=True)


def plan_size(packages: list[Package]) -> dict[str, int]:
    """Byte totals for a consent prompt, before anything is downloaded."""
    download = 0
    for p in packages:
        a = p.archive_for_host()
        if a:
            download += a.size
    return {
        "downloadBytes": download,
        "downloadMb": round(download / (1024 * 1024)),
        # Images decompress substantially; ~2.2x is a conservative planning figure.
        "estimatedDiskMb": round(download * 2.2 / (1024 * 1024)),
        "freeDiskMb": settings.free_disk_mb(settings.SDK_ROOT),
    }
