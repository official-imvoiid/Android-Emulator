"""adb wrapper: device control buttons, file transfer, shell.

Everything the UI's control buttons and file manager need goes through here. The
emulator is deliberately reachable only via this app's own isolated SDK — adb is
launched with an explicit environment so it can never talk to (or start a server
for) a different Android SDK on the machine.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from .. import settings
from ..events import bus

# Android keycodes for the on-screen buttons every emulator has.
KEYCODES: dict[str, int] = {
    "home": 3,
    "back": 4,
    "recents": 187,
    "menu": 82,
    "power": 26,
    "volume_up": 24,
    "volume_down": 25,
    "mute": 164,
    "camera": 27,
    "call": 5,
    "end_call": 6,
    "search": 84,
    "notifications": 83,
    "brightness_up": 221,
    "brightness_down": 220,
    "media_play_pause": 85,
    "media_next": 87,
    "media_previous": 88,
    "dpad_up": 19,
    "dpad_down": 20,
    "dpad_left": 21,
    "dpad_right": 22,
    "enter": 66,
    "delete": 67,
    "tab": 61,
    "escape": 111,
    "screenshot": 120,
}


class AdbError(RuntimeError):
    pass


@dataclass
class AdbResult:
    code: int
    stdout: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def available() -> bool:
    return settings.adb_binary().exists()


async def run(args: list[str], *, timeout: float = 60.0, binary_output: bool = False) -> AdbResult | bytes:
    adb = settings.adb_binary()
    if not adb.exists():
        raise AdbError(
            "adb is not installed yet. Install the 'platform-tools' package to enable "
            "file transfer and device controls."
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            str(adb), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE if binary_output else asyncio.subprocess.STDOUT,
            env=settings.tool_env(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise AdbError(f"adb {' '.join(args)} timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise AdbError(f"Could not run adb: {exc}") from exc

    if binary_output:
        if (proc.returncode or 0) != 0:
            raise AdbError((err or b"").decode("utf-8", errors="replace").strip() or "adb failed")
        return out
    return AdbResult(code=proc.returncode or 0, stdout=(out or b"").decode("utf-8", errors="replace"))


async def devices() -> list[dict[str, str]]:
    if not available():
        return []
    try:
        result = await run(["devices", "-l"], timeout=20.0)
    except AdbError:
        return []
    assert isinstance(result, AdbResult)
    out: list[dict[str, str]] = []
    for line in result.stdout.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out.append({"serial": parts[0], "state": parts[1]})
    return out


async def first_emulator_serial() -> str | None:
    for d in await devices():
        if d["serial"].startswith("emulator-") and d["state"] == "device":
            return d["serial"]
    return None


async def _serial_args(serial: str | None) -> list[str]:
    target = serial or await first_emulator_serial()
    if not target:
        raise AdbError("No running emulator found. Start a device first.")
    return ["-s", target]


async def wait_for_boot(serial: str | None = None, timeout: float = 300.0) -> bool:
    """Poll sys.boot_completed. First boot of a fresh image can take minutes."""
    if not available():
        return False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            target = serial or await first_emulator_serial()
            if target:
                result = await run(["-s", target, "shell", "getprop", "sys.boot_completed"], timeout=15.0)
                assert isinstance(result, AdbResult)
                if result.stdout.strip() == "1":
                    bus.publish("device", state="booted", serial=target)
                    return True
        except AdbError:
            pass
        await asyncio.sleep(3.0)
    return False


# ------------------------------------------------------------------- controls

async def key(name: str, serial: str | None = None) -> None:
    code = KEYCODES.get(name)
    if code is None:
        raise AdbError(f"Unknown control '{name}'")
    await run([*await _serial_args(serial), "shell", "input", "keyevent", str(code)], timeout=20.0)


async def text(value: str, serial: str | None = None) -> None:
    """Type text into the focused field."""
    escaped = value.replace(" ", "%s")
    await run([*await _serial_args(serial), "shell", "input", "text", shlex.quote(escaped)], timeout=30.0)


async def rotate(orientation: int, serial: str | None = None) -> None:
    """0=portrait, 1=landscape, 2=portrait flipped, 3=landscape flipped.

    Auto-rotation has to be disabled first or the sensor immediately overrides us.
    """
    args = await _serial_args(serial)
    await run([*args, "shell", "settings", "put", "system", "accelerometer_rotation", "0"], timeout=20.0)
    await run([*args, "shell", "settings", "put", "system", "user_rotation", str(orientation % 4)], timeout=20.0)


async def screenshot(serial: str | None = None) -> bytes:
    data = await run([*await _serial_args(serial), "exec-out", "screencap", "-p"],
                     timeout=60.0, binary_output=True)
    assert isinstance(data, bytes)
    return data


async def set_battery(level: int, serial: str | None = None) -> None:
    args = await _serial_args(serial)
    level = max(0, min(100, level))
    await run([*args, "shell", "dumpsys", "battery", "set", "level", str(level)], timeout=20.0)


async def reset_battery(serial: str | None = None) -> None:
    await run([*await _serial_args(serial), "shell", "dumpsys", "battery", "reset"], timeout=20.0)


async def install_apk(local_path: str, serial: str | None = None) -> str:
    result = await run([*await _serial_args(serial), "install", "-r", local_path], timeout=600.0)
    assert isinstance(result, AdbResult)
    if not result.ok or "Failure" in result.stdout:
        raise AdbError(result.stdout.strip() or "APK install failed")
    return result.stdout.strip()


async def shell(command: str, serial: str | None = None, timeout: float = 60.0) -> str:
    result = await run([*await _serial_args(serial), "shell", command], timeout=timeout)
    assert isinstance(result, AdbResult)
    return result.stdout


# --------------------------------------------------------------- file transfer

_SAFE_ROOTS = ("/sdcard", "/storage/emulated", "/data/local/tmp")


def _validate_device_path(path: str) -> str:
    """Keep transfers inside user-writable areas.

    Play Store images are Play-certified, so the system partition is read-only and
    writing there fails confusingly rather than usefully. Restricting up front
    turns that into a clear message.
    """
    if not path.startswith("/"):
        raise AdbError("Device paths must be absolute, e.g. /sdcard/Download")
    normalised = str(PurePosixPath(path))
    if ".." in PurePosixPath(normalised).parts:
        raise AdbError("Device path may not contain '..'")
    if not any(normalised == r or normalised.startswith(r + "/") for r in _SAFE_ROOTS):
        raise AdbError(
            f"For safety, transfers are limited to {', '.join(_SAFE_ROOTS)}. "
            "The system partition is read-only on Play Store images."
        )
    return normalised


async def list_dir(device_path: str = "/sdcard", serial: str | None = None) -> dict[str, Any]:
    target = _validate_device_path(device_path)
    result = await run([*await _serial_args(serial), "shell", "ls", "-lA", shlex.quote(target)], timeout=45.0)
    assert isinstance(result, AdbResult)

    entries: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.rstrip()
        if not line or line.startswith("total "):
            continue
        if "No such file" in line or "Permission denied" in line:
            raise AdbError(line.strip())
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        mode, _links, owner, group, size, date, time_, name = parts
        is_dir = mode.startswith("d")
        entries.append({
            "name": name,
            "isDir": is_dir,
            "size": 0 if is_dir else int(size) if size.isdigit() else 0,
            "modified": f"{date} {time_}",
            "mode": mode,
            "path": str(PurePosixPath(target) / name),
        })
    entries.sort(key=lambda e: (not e["isDir"], e["name"].lower()))

    parent = str(PurePosixPath(target).parent)
    return {
        "path": target,
        "parent": parent if target not in _SAFE_ROOTS and parent != target else None,
        "entries": entries,
    }


async def push(local_path: str, device_dir: str, serial: str | None = None) -> str:
    from pathlib import Path

    source = Path(local_path).expanduser()
    if not source.exists():
        raise AdbError(f"Local file not found: {source}")
    target = _validate_device_path(device_dir)
    result = await run(
        [*await _serial_args(serial), "push", str(source), f"{target}/{source.name}"],
        timeout=1800.0,
    )
    assert isinstance(result, AdbResult)
    if not result.ok:
        raise AdbError(result.stdout.strip() or "push failed")
    bus.log(f"Copied {source.name} to device {target}")
    return result.stdout.strip()


async def pull(device_path: str, local_dir: str, serial: str | None = None) -> str:
    from pathlib import Path

    source = _validate_device_path(device_path)
    dest = Path(local_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    result = await run(
        [*await _serial_args(serial), "pull", source, str(dest)],
        timeout=1800.0,
    )
    assert isinstance(result, AdbResult)
    if not result.ok:
        raise AdbError(result.stdout.strip() or "pull failed")
    bus.log(f"Copied {source} to {dest}")
    return result.stdout.strip()


async def kill_server() -> None:
    if available():
        try:
            await run(["kill-server"], timeout=20.0)
        except AdbError:
            pass
