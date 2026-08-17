"""Host capability, acceleration and support-window endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import settings
from ..core import accel, avd, versions

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info")
async def info() -> dict[str, Any]:
    return {
        "host": {
            "os": settings.host_os(),
            "arch": settings.host_arch(),
            "guestAbi": settings.host_abi(),
            "logicalCpus": settings.logical_cpus(),
            "totalRamMb": settings.total_ram_mb(),
            "freeDiskMb": settings.free_disk_mb(settings.SDK_ROOT),
        },
        "paths": {
            "home": str(settings.HOME),
            "sdkRoot": str(settings.SDK_ROOT),
            "avdHome": str(settings.AVD_HOME),
            "tempHome": str(settings.TMP_HOME),
            "emulator": str(settings.emulator_binary()),
            "adb": str(settings.adb_binary()),
        },
        "isolation": (
            "Everything this app downloads or creates lives under the single root "
            "shown above. Your existing Android SDK, ~/.android, PATH and system "
            "environment are never modified."
        ),
        "support": versions.support_summary(),
        "repository": settings.REPO_BASE,
    }


@router.get("/accel")
async def acceleration() -> dict[str, Any]:
    return await accel.status()


@router.get("/options")
async def options() -> dict[str, Any]:
    """Bounds and choices for the hardware picker, derived from this machine."""
    cpus = settings.logical_cpus()
    ram = settings.total_ram_mb()
    return {
        "deviceProfiles": [p.to_dict() for p in avd.DEVICE_PROFILES],
        "gpuModes": avd.GPU_MODES,
        "ram": {
            "min": 1536,
            "max": min(8192, max(2048, ram - 2048)),
            "step": 512,
            "default": min(4096, max(2048, ram // 4)),
            "hostTotalMb": ram,
            "note": "The emulator accepts 1536–8192 MB. Android 17 images require at least 4096 MB.",
        },
        "cores": {
            "min": 1,
            "max": max(1, cpus - 2) if cpus > 3 else cpus,
            "default": min(4, max(1, cpus // 2)),
            "hostLogicalCpus": cpus,
        },
        "storage": {"min": 2, "max": 128, "step": 2, "default": 8, "unit": "GB",
                    "note": "Sparse — space is used as the device fills it, not reserved up front."},
        "persistence": [
            {"id": "persistent", "name": "Persistent",
             "detail": "Apps, files and settings survive restarts. Uses quick boot."},
            {"id": "temporary", "name": "Temporary",
             "detail": "Factory-fresh every launch, wiped on exit. The downloaded Android "
                       "image is shared, so nothing is re-downloaded."},
        ],
    }


@router.post("/cleanup")
async def cleanup() -> dict[str, Any]:
    removed = avd.cleanup_stale_temp_sessions()
    return {"removedTempSessions": removed}
