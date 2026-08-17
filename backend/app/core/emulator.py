"""Emulator process lifecycle."""
from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

from .. import settings
from ..events import bus
from . import adb, avd

# GPU modes that are passed on the command line rather than through config.ini.
_CLI_GPU_MODES = {"swiftshader_indirect", "angle_indirect", "host", "auto"}


@dataclass
class RunningDevice:
    session: avd.AvdSession
    process: asyncio.subprocess.Process
    argv: list[str]
    serial: str | None = None
    booted: bool = False
    log_tail: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        spec = self.session.spec
        return {
            "name": spec.name,
            "packagePath": spec.package_path,
            "apiLevel": spec.api_level_raw,
            "ramMb": spec.ram_mb,
            "cores": spec.cores,
            "storageGb": spec.storage_gb,
            "gpuMode": spec.gpu_mode,
            "deviceProfile": spec.device_profile,
            "persistent": spec.persistent,
            "playStore": spec.play_store,
            "headless": spec.headless,
            "ephemeral": self.session.ephemeral,
            "pid": self.process.pid,
            "running": self.process.returncode is None,
            "serial": self.serial,
            "booted": self.booted,
            "notes": spec.notes,
        }


class EmulatorManager:
    """One device at a time.

    A second concurrent instance is possible with `-read-only` and distinct ports,
    but it doubles RAM and GPU pressure and complicates adb targeting, so the UI
    keeps a single device and this class enforces it.
    """

    def __init__(self) -> None:
        self._device: RunningDevice | None = None
        self._lock = asyncio.Lock()

    @property
    def device(self) -> RunningDevice | None:
        if self._device and self._device.process.returncode is not None:
            return None
        return self._device

    def build_argv(self, session: avd.AvdSession) -> list[str]:
        spec = session.spec
        binary = settings.emulator_binary()
        argv = [str(binary), "-avd", spec.name]

        if spec.gpu_mode in _CLI_GPU_MODES:
            argv += ["-gpu", spec.gpu_mode]

        ram, _ = avd.clamp_ram(spec.ram_mb, None)
        argv += ["-memory", str(ram)]

        if spec.headless:
            # No native window; this app mirrors the screen over adb instead.
            argv += ["-no-window"]

        if not spec.persistent:
            # Temporary session: never load or save a snapshot, and factory-reset
            # userdata on every boot. The shared system image is untouched.
            argv += ["-no-snapshot", "-wipe-data"]

        argv += ["-netdelay", "none", "-netspeed", "full"]
        return argv

    async def start(self, spec: avd.AvdSpec) -> RunningDevice:
        async with self._lock:
            if self.device is not None:
                raise RuntimeError("A device is already running. Stop it before starting another.")

            binary = settings.emulator_binary()
            if not binary.exists():
                raise RuntimeError(
                    "The emulator is not installed yet. Install an Android version first."
                )

            image_dir = settings.SDK_ROOT.joinpath(*spec.package_path.split(";"))
            if not image_dir.exists():
                raise RuntimeError(
                    f"System image for {spec.package_path} is missing. Install it first."
                )

            session = avd.create_session(spec)
            argv = self.build_argv(session)

            env = settings.tool_env()
            # Point the emulator at this session's AVD home so an ephemeral run
            # cannot see or disturb persistent devices.
            env["ANDROID_AVD_HOME"] = str(session.avd_home)

            bus.log(f"Launching: {' '.join(argv)}")
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env=env,
                    cwd=str(binary.parent),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except OSError as exc:
                session.cleanup()
                raise RuntimeError(f"Could not start the emulator: {exc}") from exc

            device = RunningDevice(session=session, process=process, argv=argv)
            self._device = device

            bus.publish("device", state="starting", name=spec.name)
            asyncio.create_task(self._pump_logs(device))
            asyncio.create_task(self._watch_boot(device))
            return device

    async def _pump_logs(self, device: RunningDevice) -> None:
        stream = device.process.stdout
        if stream is None:
            return
        try:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                device.log_tail.append(line)
                if len(device.log_tail) > 300:
                    del device.log_tail[:100]
                level = "error" if ("ERROR" in line or "PANIC" in line) else "info"
                bus.log(f"[emulator] {line}", level)
        except (asyncio.CancelledError, OSError):
            pass
        finally:
            code = await device.process.wait()
            bus.publish("device", state="stopped", name=device.session.spec.name, exitCode=code)
            bus.log(f"Emulator exited with code {code}")
            device.session.cleanup()
            if self._device is device:
                self._device = None

    async def _watch_boot(self, device: RunningDevice) -> None:
        if not adb.available():
            bus.log(
                "platform-tools is not installed, so boot detection, file transfer and "
                "device controls are unavailable. Install it from the Packages tab.",
                "warn",
            )
            return
        booted = await adb.wait_for_boot(timeout=420.0)
        if device.process.returncode is not None:
            return
        device.booted = booted
        device.serial = await adb.first_emulator_serial()
        if booted:
            bus.log("Device finished booting.")
        else:
            bus.log("Device did not report a completed boot in time.", "warn")

    async def stop(self) -> bool:
        async with self._lock:
            device = self.device
            if device is None:
                return False

            bus.publish("device", state="stopping", name=device.session.spec.name)

            # Graceful shutdown first so persistent devices flush their state.
            if adb.available() and device.serial:
                try:
                    await adb.run(["-s", device.serial, "emu", "kill"], timeout=20.0)
                except adb.AdbError:
                    pass

            try:
                await asyncio.wait_for(device.process.wait(), timeout=20.0)
            except asyncio.TimeoutError:
                bus.log("Emulator did not exit cleanly; terminating.", "warn")
                try:
                    device.process.terminate()
                    await asyncio.wait_for(device.process.wait(), timeout=10.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        device.process.kill()
                    except ProcessLookupError:
                        pass
            return True


manager = EmulatorManager()
