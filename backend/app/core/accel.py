"""Hardware acceleration detection.

Windows acceleration consolidated recently and only one option has a future:
  WHPX  (Windows Hypervisor Platform)  -- the go-forward path
  AEHD  (Android Emulator Hypervisor Driver) -- sunsets 31 December 2026
  HAXM  -- removed from the emulator in v36.2.11

So we detect WHPX, tell the user how to enable it, and never offer to install AEHD.
Without acceleration the emulator still runs, but via CPU emulation that is far too
slow to be usable — so this check gates the "ready to boot" state.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from typing import Any

from .. import settings


async def _run(cmd: list[str], timeout: float = 25.0) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=settings.tool_env(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode("utf-8", errors="replace")
    except (FileNotFoundError, asyncio.TimeoutError, OSError) as exc:
        return -1, str(exc)


async def _windows_features() -> dict[str, bool]:
    """Read optional-feature state without needing administrator rights."""
    if os.name != "nt":
        return {}
    script = (
        "Get-CimInstance Win32_OptionalFeature "
        "| Where-Object { $_.Name -in 'HypervisorPlatform','VirtualMachinePlatform',"
        "'Microsoft-Hyper-V-Hypervisor' } "
        "| ForEach-Object { \"$($_.Name)=$($_.InstallState)\" }"
    )
    code, out = await _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    features: dict[str, bool] = {}
    if code == 0:
        for line in out.splitlines():
            if "=" in line:
                name, _, state = line.strip().partition("=")
                features[name] = state.strip() == "1"  # 1 == Enabled
    return features


async def status() -> dict[str, Any]:
    """Best-effort acceleration report, plus what to do about it."""
    emulator = settings.emulator_binary()
    report: dict[str, Any] = {
        "platform": settings.host_os(),
        "hostArch": settings.host_arch(),
        "guestAbi": settings.host_abi(),
        "logicalCpus": settings.logical_cpus(),
        "totalRamMb": settings.total_ram_mb(),
        "freeDiskMb": settings.free_disk_mb(settings.SDK_ROOT),
        "emulatorInstalled": emulator.exists(),
        "accelerated": None,
        "detail": "",
        "features": {},
        "fixCommand": None,
        "aehdNotice": (
            "AEHD (the Android Emulator hypervisor driver) sunsets on 31 December 2026 "
            "and HAXM was removed in emulator 36.2.11, so WHPX is the only Windows "
            "acceleration path with a future. This app never installs AEHD."
        ) if settings.host_os() == "windows" else None,
    }

    if settings.host_os() == "windows":
        features = await _windows_features()
        report["features"] = features
        if features and not features.get("HypervisorPlatform", False):
            report["accelerated"] = False
            report["detail"] = (
                "Windows Hypervisor Platform (WHPX) is disabled. Without it the emulator "
                "falls back to CPU emulation and is unusably slow."
            )
            report["fixCommand"] = (
                "dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart"
            )

    # The emulator's own check is authoritative, so prefer it when installed.
    if emulator.exists():
        code, out = await _run([str(emulator), "-accel-check"])
        text = out.strip()
        report["accelCheckOutput"] = text
        lowered = text.lower()
        if "is installed and usable" in lowered or code == 0 and "not" not in lowered:
            report["accelerated"] = True
            report["detail"] = text or "Hardware acceleration is available."
            report["fixCommand"] = None
        elif text:
            report["accelerated"] = False
            report["detail"] = text

    if report["accelerated"] is None and not emulator.exists():
        report["detail"] = "Install the emulator to run a full acceleration check."

    return report
