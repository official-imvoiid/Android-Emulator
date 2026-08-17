"""Fetching and parsing Google's SDK repository manifests.

Two rules make this survive Google's changes:

1. Namespace-agnostic XPath. The manifests declare versioned namespaces
   (`.../repository2/03`) that Google has bumped before and will again, so every
   lookup uses `local-name()` instead of a bound prefix.

2. Nothing is hardcoded but the base URL. Filenames, schema versions, package
   paths, download URLs, sizes and checksums are all read from the live manifests.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .. import settings

CHANNEL_NAMES = {0: "stable", 1: "beta", 2: "dev", 3: "canary"}


# ------------------------------------------------------------------- data model

@dataclass
class Archive:
    url: str            # absolute, already resolved against the manifest's own dir
    size: int
    checksum: str
    checksum_type: str  # read from the attribute; do not assume sha1 forever
    host_os: str | None
    host_arch: str | None


@dataclass
class Package:
    path: str                      # "system-images;android-36;google_apis_playstore;x86_64"
    display_name: str
    revision: tuple[int, ...]
    channel: str                   # stable | beta | dev | canary
    api_level_raw: str | None
    codename: str | None           # non-empty means a preview build
    abi: str | None
    tags: list[str] = field(default_factory=list)
    extension_level: int | None = None
    base_extension: bool = True
    archives: list[Archive] = field(default_factory=list)
    dependencies: dict[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def revision_str(self) -> str:
        return ".".join(str(p) for p in self.revision)

    @property
    def is_preview(self) -> bool:
        return bool(self.codename) or self.channel != "stable"

    def archive_for_host(self) -> Archive | None:
        """Pick the archive matching this machine.

        Some packages ship one archive per OS; others ship a single universal
        archive with the host attributes absent. Both shapes occur in the same
        manifest, so handle both.
        """
        want_os, want_arch = settings.host_os(), settings.host_arch()
        universal: Archive | None = None
        for a in self.archives:
            if a.host_os is None and a.host_arch is None:
                universal = universal or a
                continue
            if a.host_os and a.host_os != want_os:
                continue
            if a.host_arch and a.host_arch != want_arch:
                continue
            return a
        return universal

    def install_dir(self, sdk_root: Path) -> Path:
        """Where the package lands. Package path maps 1:1 onto directories."""
        return sdk_root.joinpath(*self.path.split(";"))


# ------------------------------------------------------------------ XML helpers

def _child(node: ET.Element, name: str) -> ET.Element | None:
    for c in node:
        if c.tag.rpartition("}")[2] == name:
            return c
    return None


def _children(node: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in node if c.tag.rpartition("}")[2] == name]


def _text(node: ET.Element | None, name: str) -> str | None:
    if node is None:
        return None
    c = _child(node, name)
    return (c.text or "").strip() if c is not None else None


def _findall_local(root: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in root.iter() if e.tag.rpartition("}")[2] == name]


def _revision(node: ET.Element | None) -> tuple[int, ...]:
    if node is None:
        return (0,)
    parts: list[int] = []
    for key in ("major", "minor", "micro", "preview"):
        val = _text(node, key)
        if val is None:
            continue
        try:
            parts.append(int(val))
        except ValueError:
            pass
    return tuple(parts) or (0,)


# ---------------------------------------------------------------------- fetching

def _cache_path(url: str) -> Path:
    safe = url.replace("https://", "").replace("/", "_").replace(":", "_")
    return settings.CACHE_DIR / safe


async def fetch_text(client: httpx.AsyncClient, url: str, *, use_cache: bool = True) -> str | None:
    """Fetch a manifest, with a short-lived on-disk cache. None on 404."""
    cache = _cache_path(url)
    if use_cache and cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < settings.MANIFEST_TTL_SECONDS:
            return cache.read_text(encoding="utf-8", errors="replace")

    try:
        resp = await client.get(url, timeout=45.0, follow_redirects=True)
    except httpx.HTTPError:
        # Offline: a stale cache beats no catalog at all.
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="replace")
        return None

    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        if cache.exists():
            return cache.read_text(encoding="utf-8", errors="replace")
        return None

    settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


async def url_exists(client: httpx.AsyncClient, url: str) -> bool:
    try:
        resp = await client.head(url, timeout=20.0, follow_redirects=True)
        if resp.status_code < 400:
            return True
        if resp.status_code in (403, 405):  # some hosts dislike HEAD
            resp = await client.get(url, timeout=20.0, follow_redirects=True)
            return resp.status_code < 400
        return False
    except httpx.HTTPError:
        return False


# ----------------------------------------------------------------------- parsing

def parse_packages(xml_text: str, manifest_url: str) -> list[Package]:
    """Turn one manifest into Package objects."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    channels: dict[str, str] = {}
    for ch in _findall_local(root, "channel"):
        cid = ch.get("id") or ""
        channels[cid] = (ch.text or "stable").strip()

    packages: list[Package] = []
    for node in _findall_local(root, "remotePackage"):
        path = node.get("path")
        if not path:
            continue

        details = _child(node, "type-details")
        tags: list[str] = []
        if details is not None:
            for tag in _children(details, "tag"):
                tid = _text(tag, "id")
                if tid:
                    tags.append(tid)

        ext_raw = _text(details, "extension-level") if details is not None else None
        try:
            ext_level = int(ext_raw) if ext_raw else None
        except ValueError:
            ext_level = None

        base_ext_raw = _text(details, "base-extension") if details is not None else None
        base_ext = base_ext_raw != "false"

        ch_ref = _child(node, "channelRef")
        channel = channels.get(ch_ref.get("ref", ""), "stable") if ch_ref is not None else "stable"

        archives: list[Archive] = []
        arch_root = _child(node, "archives")
        for a in _children(arch_root, "archive") if arch_root is not None else []:
            complete = _child(a, "complete")
            if complete is None:
                continue
            rel_url = _text(complete, "url")
            size_raw = _text(complete, "size")
            checksum_node = _child(complete, "checksum")
            if not rel_url or checksum_node is None:
                continue
            try:
                size = int(size_raw or 0)
            except ValueError:
                size = 0
            archives.append(
                Archive(
                    url=urljoin(manifest_url, rel_url),
                    size=size,
                    checksum=(checksum_node.text or "").strip(),
                    checksum_type=(checksum_node.get("type") or "sha1").lower(),
                    host_os=_text(a, "host-os"),
                    host_arch=_text(a, "host-arch"),
                )
            )
        if not archives:
            continue

        deps: dict[str, tuple[int, ...]] = {}
        dep_root = _child(node, "dependencies")
        for d in _children(dep_root, "dependency") if dep_root is not None else []:
            dpath = d.get("path")
            if dpath:
                deps[dpath] = _revision(_child(d, "min-revision"))

        packages.append(
            Package(
                path=path,
                display_name=_text(node, "display-name") or path,
                revision=_revision(_child(node, "revision")),
                channel=channel,
                api_level_raw=_text(details, "api-level") if details is not None else None,
                codename=_text(details, "codename") if details is not None else None,
                abi=_text(details, "abi") if details is not None else None,
                tags=tags,
                extension_level=ext_level,
                base_extension=base_ext,
                archives=archives,
                dependencies=deps,
            )
        )
    return packages
