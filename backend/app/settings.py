"""Paths and tunables.

Everything the tool creates lives under one isolated root. Nothing is written to the
user's existing Android SDK, ~/.android, or system environment.
"""
from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

# Google's SDK repository. Only the base is fixed; every filename below it is
# discovered at runtime (see core/discovery.py) so new releases need no code change.
REPO_BASE = "https://dl.google.com/android/repository/"

# Highest schema version to probe for, walking downwards until one responds.
# Raise these if Google ever gets ahead of us; the probe handles the rest.
MAX_ADDONS_LIST = 12
MAX_REPO_SCHEMA = 10
MAX_SYSIMG_SCHEMA = 10

# Manifest cache lifetime. Canary images land weekly, so a few hours is plenty.
MANIFEST_TTL_SECONDS = 6 * 3600


def _default_home() -> Path:
    """A short, isolated root.

    Deliberately short: extracted system images nest deeply and Windows' 260-char
    path limit is a real failure mode under a long path like Downloads/....
    """
    if os.name == "nt":
        drive = os.environ.get("SystemDrive", "C:")
        return Path(f"{drive}\\AndroidEmulatorHub")
    return Path.home() / ".android-emulator-hub"


HOME = Path(os.environ.get("EMUHUB_HOME", "")).expanduser() if os.environ.get("EMUHUB_HOME") else _default_home()

SDK_ROOT = HOME / "sdk"           # ANDROID_SDK_ROOT
AVD_HOME = HOME / "avd"           # ANDROID_AVD_HOME (persistent sessions)
TMP_HOME = HOME / "tmp"           # ephemeral AVD homes, deleted on stop
CACHE_DIR = HOME / "cache"        # manifest XML cache
DOWNLOAD_DIR = HOME / "downloads"  # zip staging, resumable
STATE_DIR = HOME / "state"        # installed-package markers, saved profiles

_ALL_DIRS = (HOME, SDK_ROOT, AVD_HOME, TMP_HOME, CACHE_DIR, DOWNLOAD_DIR, STATE_DIR)


def ensure_dirs() -> None:
    for d in _ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- host identity

def host_os() -> str:
    """The value Google uses in <host-os>."""
    return {"Windows": "windows", "Linux": "linux", "Darwin": "macosx"}.get(platform.system(), "linux")


def host_arch() -> str:
    """The value Google uses in <host-arch>."""
    m = platform.machine().lower()
    if m in ("arm64", "aarch64"):
        return "aarch64"
    return "x64"


def host_abi() -> str:
    """The guest ABI that can actually be hardware-accelerated on this host.

    Running an arm64 image on x86 (or vice versa) falls back to full CPU
    translation and is unusably slow, so we filter rather than offer it.
    """
    return "arm64-v8a" if host_arch() == "aarch64" else "x86_64"


def logical_cpus() -> int:
    return os.cpu_count() or 2


def total_ram_mb() -> int:
    try:
        if os.name == "nt":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys // (1024 * 1024))
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024))
    except Exception:
        return 8192


def free_disk_mb(path: Path | None = None) -> int:
    target = path or HOME
    probe = target
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return int(shutil.disk_usage(probe).free // (1024 * 1024))
    except Exception:
        return 0


# ------------------------------------------------------------------ tool paths

def emulator_binary() -> Path:
    exe = "emulator.exe" if os.name == "nt" else "emulator"
    return SDK_ROOT / "emulator" / exe


def adb_binary() -> Path:
    exe = "adb.exe" if os.name == "nt" else "adb"
    return SDK_ROOT / "platform-tools" / exe


def tool_env() -> dict[str, str]:
    """Environment for spawned emulator/adb processes.

    Set explicitly rather than inherited so an existing Android SDK on the machine
    can never be picked up, modified, or interfered with.
    """
    env = dict(os.environ)
    env["ANDROID_SDK_ROOT"] = str(SDK_ROOT)
    env["ANDROID_HOME"] = str(SDK_ROOT)      # older tools still read this
    env["ANDROID_AVD_HOME"] = str(AVD_HOME)
    env["ANDROID_EMULATOR_HOME"] = str(HOME)
    return env
