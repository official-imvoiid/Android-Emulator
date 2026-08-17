"""Generating AVDs.

An AVD is two text files: a pointer `<name>.ini` and a `<name>.avd/config.ini`
hardware definition. Google's own android-emulator-container-scripts ships a
templated config.ini, so writing it directly is the sanctioned approach — and it
avoids `avdmanager`, which is a Java program that has no flags for RAM, CPU cores
or storage anyway.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import settings
from ..events import bus
from . import versions

# hw.cpu.arch is not the same string as the image ABI.
_CPU_ARCH = {"x86_64": "x86_64", "x86": "x86", "arm64-v8a": "arm64", "armeabi-v7a": "arm"}

# Emulator 36.6.11 raised the floor to 4 GB for API 37 images. Booting below the
# floor fails in ways that look like a corrupt image, so enforce it up front.
_RAM_FLOOR_BY_API = {37: 4096}
_RAM_FLOOR_DEFAULT = 2048
_RAM_MIN = 1536
_RAM_MAX = 8192


@dataclass
class DeviceProfile:
    id: str
    name: str
    width: int
    height: int
    density: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "width": self.width,
                "height": self.height, "density": self.density}


DEVICE_PROFILES: list[DeviceProfile] = [
    DeviceProfile("phone", "Phone — 1080 x 2400", 1080, 2400, 420),
    DeviceProfile("phone_compact", "Compact phone — 1080 x 2160", 1080, 2160, 400),
    DeviceProfile("phone_large", "Large phone — 1440 x 3120", 1440, 3120, 560),
    DeviceProfile("tablet", "Tablet — 1600 x 2560", 1600, 2560, 320),
    DeviceProfile("desktop", "Desktop — 1920 x 1080", 1920, 1080, 160),
]

GPU_MODES = [
    {"id": "auto", "name": "Dynamic (recommended)",
     "detail": "Emulator picks the host GPU and falls back on its own."},
    {"id": "host", "name": "Host GPU",
     "detail": "Direct host OpenGL. Fastest, most sensitive to graphics drivers."},
    {"id": "angle_indirect", "name": "ANGLE (Direct3D 11)",
     "detail": "Translates OpenGL to D3D11. Often the best choice on Windows."},
    {"id": "swiftshader_indirect", "name": "Software (emulated)",
     "detail": "CPU rendering. Slow but works on any machine."},
]


def profile_by_id(profile_id: str) -> DeviceProfile:
    for p in DEVICE_PROFILES:
        if p.id == profile_id:
            return p
    return DEVICE_PROFILES[0]


def ram_floor_for(api_major: int | None) -> int:
    if api_major is None:
        return _RAM_FLOOR_DEFAULT
    return _RAM_FLOOR_BY_API.get(api_major, _RAM_FLOOR_DEFAULT)


def clamp_ram(ram_mb: int, api_major: int | None) -> tuple[int, str | None]:
    floor = max(ram_floor_for(api_major), _RAM_MIN)
    note = None
    value = ram_mb
    if value < floor:
        note = f"RAM raised to {floor} MB — the minimum this Android version boots with."
        value = floor
    if value > _RAM_MAX:
        note = f"RAM capped at {_RAM_MAX} MB — the emulator's maximum."
        value = _RAM_MAX
    return value, note


def clamp_cores(cores: int) -> int:
    return max(1, min(cores, max(1, settings.logical_cpus())))


@dataclass
class AvdSpec:
    name: str
    package_path: str            # "system-images;android-36;google_apis_playstore;x86_64"
    api_level_raw: str
    ram_mb: int = 4096
    cores: int = 4
    storage_gb: int = 8
    gpu_mode: str = "auto"
    device_profile: str = "phone"
    persistent: bool = True
    play_store: bool = True
    # False = the emulator opens its own window (with its own control sidebar).
    # True = no window at all; the screen is mirrored inside this app instead,
    # so you are not looking at the same device twice.
    headless: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class AvdSession:
    spec: AvdSpec
    avd_home: Path
    avd_dir: Path
    ephemeral: bool

    def cleanup(self) -> None:
        """Remove an ephemeral session. The shared system image is untouched."""
        if not self.ephemeral:
            return
        shutil.rmtree(self.avd_home, ignore_errors=True)


def _sysdir(package_path: str) -> str:
    """image.sysdir.1 — SDK-root-relative, forward slashes, trailing slash.

    Required even on Windows; backslashes here silently fail to resolve.
    """
    return "/".join(package_path.split(";")) + "/"


def _tag_from_path(package_path: str) -> str:
    parts = package_path.split(";")
    return parts[2] if len(parts) >= 3 else "google_apis_playstore"


def _abi_from_path(package_path: str) -> str:
    parts = package_path.split(";")
    return parts[3] if len(parts) >= 4 else settings.host_abi()


def _tag_display(tag: str) -> str:
    return {
        "google_apis_playstore": "Google Play",
        "google_apis": "Google APIs",
        "android": "Default Android System Image",
    }.get(tag, tag)


def build_config_ini(spec: AvdSpec) -> str:
    api = versions.parse_api_level(spec.api_level_raw)
    ram, ram_note = clamp_ram(spec.ram_mb, api.major)
    if ram_note and ram_note not in spec.notes:
        spec.notes.append(ram_note)
    cores = clamp_cores(spec.cores)
    profile = profile_by_id(spec.device_profile)
    tag = _tag_from_path(spec.package_path)
    abi = _abi_from_path(spec.package_path)

    # Play Store is only available on playstore-tagged images. Asking for it on
    # any other image produces a device with no Play Store and no explanation.
    play_store = spec.play_store and "playstore" in tag

    lines = [
        f"AvdId={spec.name}",
        f"avd.ini.displayname={spec.name}",
        "avd.ini.encoding=UTF-8",
        f"PlayStore.enabled={'true' if play_store else 'false'}",
        f"abi.type={abi}",
        f"hw.cpu.arch={_CPU_ARCH.get(abi, abi)}",
        f"hw.cpu.ncore={cores}",
        f"hw.ramSize={ram}",
        f"vm.heapSize={max(256, min(576, ram // 8))}",
        f"disk.dataPartition.size={spec.storage_gb}G",
        f"image.sysdir.1={_sysdir(spec.package_path)}",
        f"tag.id={tag}",
        f"tag.display={_tag_display(tag)}",
        "hw.gpu.enabled=yes",
        f"hw.gpu.mode={spec.gpu_mode if spec.gpu_mode in ('auto', 'host') else 'auto'}",
        f"hw.lcd.width={profile.width}",
        f"hw.lcd.height={profile.height}",
        f"hw.lcd.density={profile.density}",
        "hw.initialOrientation=Portrait",
        "hw.keyboard=yes",
        "hw.mainKeys=no",
        "hw.dPad=no",
        "hw.trackBall=no",
        "hw.accelerometer=yes",
        "hw.sensors.orientation=yes",
        "hw.sensors.proximity=yes",
        "hw.gps=yes",
        "hw.battery=yes",
        "hw.audioInput=yes",
        "hw.camera.back=emulated",
        "hw.camera.front=emulated",
        "hw.device.manufacturer=Google",
        "runtime.network.latency=none",
        "runtime.network.speed=full",
        # Ephemeral sessions always cold boot; persistent ones use quick boot.
        f"fastboot.forceColdBoot={'no' if spec.persistent else 'yes'}",
    ]
    return "\n".join(lines) + "\n"


def create_session(spec: AvdSpec) -> AvdSession:
    """Write the AVD to disk.

    Persistent sessions live in the shared AVD home. Ephemeral sessions get a
    private AVD home under tmp/ so only the small userdata overlay is temporary —
    the multi-gigabyte system image stays shared and is never re-downloaded.
    """
    settings.ensure_dirs()

    if spec.persistent:
        avd_home = settings.AVD_HOME
        ephemeral = False
    else:
        avd_home = settings.TMP_HOME / f"session-{int(time.time() * 1000)}"
        ephemeral = True

    avd_home.mkdir(parents=True, exist_ok=True)
    avd_dir = avd_home / f"{spec.name}.avd"
    avd_dir.mkdir(parents=True, exist_ok=True)

    (avd_dir / "config.ini").write_text(build_config_ini(spec), encoding="utf-8")

    pointer = "\n".join([
        "avd.ini.encoding=UTF-8",
        f"path={avd_dir}",
        f"path.rel=avd/{spec.name}.avd",
        f"target=android-{versions.parse_api_level(spec.api_level_raw).raw}",
    ]) + "\n"
    (avd_home / f"{spec.name}.ini").write_text(pointer, encoding="utf-8")

    bus.log(f"Created AVD '{spec.name}' ({'persistent' if spec.persistent else 'temporary'})")
    return AvdSession(spec=spec, avd_home=avd_home, avd_dir=avd_dir, ephemeral=ephemeral)


def list_persistent_avds() -> list[dict[str, Any]]:
    if not settings.AVD_HOME.exists():
        return []
    out: list[dict[str, Any]] = []
    for ini in sorted(settings.AVD_HOME.glob("*.ini")):
        name = ini.stem
        config = settings.AVD_HOME / f"{name}.avd" / "config.ini"
        data: dict[str, str] = {}
        if config.exists():
            for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    data[k.strip()] = v.strip()
        out.append({
            "name": name,
            "ramMb": int(data.get("hw.ramSize", 0) or 0),
            "cores": int(data.get("hw.cpu.ncore", 0) or 0),
            "storage": data.get("disk.dataPartition.size", ""),
            "sysdir": data.get("image.sysdir.1", ""),
            "playStore": data.get("PlayStore.enabled") == "true",
            "gpuMode": data.get("hw.gpu.mode", "auto"),
            "resolution": f"{data.get('hw.lcd.width', '?')}x{data.get('hw.lcd.height', '?')}",
        })
    return out


def delete_persistent_avd(name: str) -> bool:
    ini = settings.AVD_HOME / f"{name}.ini"
    directory = settings.AVD_HOME / f"{name}.avd"
    existed = ini.exists() or directory.exists()
    ini.unlink(missing_ok=True)
    shutil.rmtree(directory, ignore_errors=True)
    if existed:
        bus.log(f"Deleted AVD '{name}'")
    return existed


def cleanup_stale_temp_sessions() -> int:
    """Remove ephemeral AVD homes orphaned by a crash or hard kill."""
    if not settings.TMP_HOME.exists():
        return 0
    removed = 0
    for child in settings.TMP_HOME.iterdir():
        if child.is_dir() and child.name.startswith("session-"):
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed
