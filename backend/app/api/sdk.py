"""Catalog and package-install endpoints.

The catalog is built from Google's live manifests on every request (behind a short
disk cache), which is what makes newly released Android versions appear without an
update to this app.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import settings
from ..core import discovery, download, installed, resolve
from ..events import bus

router = APIRouter(prefix="/api/sdk", tags=["sdk"])

_client: httpx.AsyncClient | None = None
_jobs: dict[str, dict[str, Any]] = {}


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            headers={"User-Agent": "AndroidEmulatorHub/1.0 (+python-httpx)"},
            follow_redirects=True,
        )
    return _client


async def shutdown_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class InstallRequest(BaseModel):
    packagePath: str = Field(..., description="e.g. system-images;android-36;google_apis_playstore;x86_64")
    includePlatformTools: bool = True


class PlanRequest(BaseModel):
    packagePath: str
    includePlatformTools: bool = True


@router.get("/catalog")
async def catalog(
    previews: bool = False,
    extensions: bool = False,
    playstoreOnly: bool = True,
    formFactor: str = "phone",
) -> dict[str, Any]:
    """The Android versions installable on this machine, read live from Google.

    `formFactor` defaults to phone because XR headset, automotive-display and
    tablet images all carry the Play Store tag too — showing them together under
    a bare "Android 14" label would boot the wrong kind of device.
    """
    cat = await resolve.build_catalog(
        client(),
        include_previews=previews,
        playstore_only=playstoreOnly,
        include_extensions=extensions,
        form_factor=(formFactor or None) if formFactor != "all" else None,
    )
    return cat.to_dict()


@router.post("/refresh")
async def refresh() -> dict[str, Any]:
    """Drop cached manifests and re-discover the repository layout."""
    discovery.invalidate()
    for f in settings.CACHE_DIR.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
    bus.log("Repository cache cleared; catalog will be re-read from Google.")
    return {"ok": True}


@router.get("/installed")
async def list_installed() -> dict[str, Any]:
    packages = installed.list_installed()
    for p in packages:
        p["diskMb"] = installed.disk_usage_mb(p.get("path", ""))
    return {
        "packages": packages,
        "emulatorInstalled": settings.emulator_binary().exists(),
        "adbInstalled": settings.adb_binary().exists(),
        "sdkRoot": str(settings.SDK_ROOT),
    }


async def _resolve_plan(package_path: str, include_platform_tools: bool):
    """Work out the full package set an image needs, honouring min-revision."""
    images = await discovery.load_system_images(client())
    image = resolve.find_package(images, package_path)
    if image is None:
        raise HTTPException(404, f"Unknown package: {package_path}")

    tools = await discovery.load_tools(client())
    min_rev = image.dependencies.get("emulator")
    emulator = resolve.pick_emulator(tools, min_rev)
    if emulator is None:
        raise HTTPException(502, "Could not find an emulator package in Google's manifest.")

    wanted = []
    if not installed.is_installed(image.path, image.revision_str):
        wanted.append(image)
    if not installed.is_installed(emulator.path, emulator.revision_str):
        wanted.append(emulator)

    if include_platform_tools:
        pt = resolve.find_package([p for p in tools if p.path == "platform-tools"], "platform-tools")
        if pt and not installed.is_installed(pt.path, pt.revision_str):
            wanted.append(pt)

    warnings: list[str] = []
    if min_rev and emulator.revision < min_rev:
        warnings.append(
            f"This image asks for emulator {'.'.join(map(str, min_rev))} or newer, but the "
            f"newest available is {emulator.revision_str}. It may not boot."
        )
    return image, emulator, wanted, warnings


@router.post("/plan")
async def plan(req: PlanRequest) -> dict[str, Any]:
    """What will be downloaded, and how big — shown before anything starts."""
    image, emulator, wanted, warnings = await _resolve_plan(req.packagePath, req.includePlatformTools)
    sizes = download.plan_size(wanted)

    if sizes["estimatedDiskMb"] > sizes["freeDiskMb"]:
        warnings.append(
            f"Estimated {sizes['estimatedDiskMb']} MB needed but only {sizes['freeDiskMb']} MB free "
            f"on the drive holding {settings.SDK_ROOT}."
        )

    return {
        **sizes,
        "packages": [
            {
                "path": p.path,
                "displayName": p.display_name,
                "revision": p.revision_str,
                "channel": p.channel,
                "sizeMb": round((p.archive_for_host().size if p.archive_for_host() else 0) / (1024 * 1024)),
            }
            for p in wanted
        ],
        "alreadyInstalled": not wanted,
        "image": {"path": image.path, "apiLevel": image.api_level_raw, "revision": image.revision_str},
        "emulator": {"path": emulator.path, "revision": emulator.revision_str, "channel": emulator.channel},
        "warnings": warnings,
    }


async def _run_install(job_id: str, package_path: str, include_platform_tools: bool) -> None:
    job = _jobs[job_id]
    try:
        _, _, wanted, _ = await _resolve_plan(package_path, include_platform_tools)
        job["total"] = len(wanted)
        for index, pkg in enumerate(wanted, start=1):
            job["current"] = pkg.path
            job["index"] = index
            await download.install_package(client(), pkg, job_id=job_id)
        job["state"] = "done"
        bus.publish("install", jobId=job_id, state="done")
    except asyncio.CancelledError:
        job["state"] = "cancelled"
        bus.publish("install", jobId=job_id, state="cancelled")
        raise
    except Exception as exc:  # surfaced to the UI rather than swallowed
        job["state"] = "error"
        job["error"] = str(exc)
        bus.log(f"Install failed: {exc}", "error")
        bus.publish("install", jobId=job_id, state="error", error=str(exc))


@router.post("/install")
async def install(req: InstallRequest) -> dict[str, Any]:
    settings.ensure_dirs()
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"state": "running", "packagePath": req.packagePath, "index": 0, "total": 0}
    task = asyncio.create_task(_run_install(job_id, req.packagePath, req.includePlatformTools))
    _jobs[job_id]["task"] = task
    bus.publish("install", jobId=job_id, state="running", packagePath=req.packagePath)
    return {"jobId": job_id}


@router.get("/install/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return {k: v for k, v in job.items() if k != "task"}


@router.post("/install/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    task = job.get("task")
    if task and not task.done():
        task.cancel()
    return {"ok": True}


@router.delete("/installed/{package_path:path}")
async def uninstall(package_path: str) -> dict[str, Any]:
    import shutil

    target = settings.SDK_ROOT.joinpath(*package_path.split(";"))
    if not target.exists():
        raise HTTPException(404, "Package is not installed")
    shutil.rmtree(target, ignore_errors=True)
    bus.log(f"Removed {package_path}")
    return {"ok": True}
