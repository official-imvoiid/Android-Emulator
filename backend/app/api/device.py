"""AVD lifecycle, boot control, and the on-screen device buttons."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from ..core import adb, avd, emulator
from ..core.avd import AvdSpec

router = APIRouter(prefix="/api", tags=["device"])

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


class StartRequest(BaseModel):
    name: str = Field("Android_Device", description="AVD name; letters, digits, _ . - only")
    packagePath: str
    apiLevel: str
    ramMb: int = 4096
    cores: int = 4
    storageGb: int = 8
    gpuMode: str = "auto"
    deviceProfile: str = "phone"
    persistent: bool = True
    playStore: bool = True
    headless: bool = False


class KeyRequest(BaseModel):
    name: str


class RotateRequest(BaseModel):
    orientation: int = Field(0, ge=0, le=3)


class TextRequest(BaseModel):
    text: str


class BatteryRequest(BaseModel):
    level: int | None = Field(None, ge=0, le=100)
    reset: bool = False


class ShellRequest(BaseModel):
    command: str


class ApkRequest(BaseModel):
    localPath: str


# ------------------------------------------------------------------------- AVDs

@router.get("/avd")
async def list_avds() -> dict[str, Any]:
    return {"avds": avd.list_persistent_avds()}


@router.delete("/avd/{name}")
async def delete_avd(name: str) -> dict[str, Any]:
    if not _NAME_RE.match(name):
        raise HTTPException(400, "Invalid AVD name")
    running = emulator.manager.device
    if running and running.session.spec.name == name:
        raise HTTPException(409, "That device is running. Stop it first.")
    if not avd.delete_persistent_avd(name):
        raise HTTPException(404, "No such AVD")
    return {"ok": True}


# ------------------------------------------------------------------- lifecycle

@router.post("/device/start")
async def start(req: StartRequest) -> dict[str, Any]:
    if not _NAME_RE.match(req.name):
        raise HTTPException(400, "Name may contain only letters, digits, underscore, dot and dash.")

    spec = AvdSpec(
        name=req.name,
        package_path=req.packagePath,
        api_level_raw=req.apiLevel,
        ram_mb=req.ramMb,
        cores=req.cores,
        storage_gb=req.storageGb,
        gpu_mode=req.gpuMode,
        device_profile=req.deviceProfile,
        persistent=req.persistent,
        play_store=req.playStore,
        headless=req.headless,
    )
    try:
        device = await emulator.manager.start(spec)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return device.to_dict()


@router.post("/device/stop")
async def stop() -> dict[str, Any]:
    stopped = await emulator.manager.stop()
    return {"stopped": stopped}


@router.get("/device/status")
async def status() -> dict[str, Any]:
    device = emulator.manager.device
    return {
        "device": device.to_dict() if device else None,
        "adbAvailable": adb.available(),
        "adbDevices": await adb.devices(),
        "logTail": device.log_tail[-40:] if device else [],
    }


# --------------------------------------------------------------------- controls

@router.get("/device/controls")
async def controls() -> dict[str, Any]:
    """The button set, grouped the way the UI lays it out."""
    return {
        "navigation": ["back", "home", "recents", "menu"],
        "power": ["power"],
        "volume": ["volume_up", "volume_down", "mute"],
        "dpad": ["dpad_up", "dpad_down", "dpad_left", "dpad_right", "enter"],
        "media": ["media_previous", "media_play_pause", "media_next"],
        "system": ["notifications", "search", "brightness_down", "brightness_up", "delete", "escape"],
        "all": sorted(adb.KEYCODES),
    }


def _require_device() -> None:
    if emulator.manager.device is None:
        raise HTTPException(409, "No device is running.")


@router.post("/device/key")
async def press_key(req: KeyRequest) -> dict[str, Any]:
    _require_device()
    try:
        await adb.key(req.name)
    except adb.AdbError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "key": req.name}


@router.post("/device/rotate")
async def rotate(req: RotateRequest) -> dict[str, Any]:
    _require_device()
    try:
        await adb.rotate(req.orientation)
    except adb.AdbError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "orientation": req.orientation}


@router.post("/device/text")
async def type_text(req: TextRequest) -> dict[str, Any]:
    _require_device()
    try:
        await adb.text(req.text)
    except adb.AdbError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@router.get("/device/screenshot")
async def screenshot() -> Response:
    _require_device()
    try:
        png = await adb.screenshot()
    except adb.AdbError as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.post("/device/battery")
async def battery(req: BatteryRequest) -> dict[str, Any]:
    _require_device()
    try:
        if req.reset or req.level is None:
            await adb.reset_battery()
        else:
            await adb.set_battery(req.level)
    except adb.AdbError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@router.post("/device/shell")
async def shell(req: ShellRequest) -> dict[str, Any]:
    """Run an adb shell command.

    Intentionally unrestricted: this is the escape hatch for anything the buttons
    don't cover. It only ever reaches the emulated device, never the host.
    """
    _require_device()
    try:
        out = await adb.shell(req.command)
    except adb.AdbError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"output": out}


@router.post("/device/install-apk")
async def install_apk(req: ApkRequest) -> dict[str, Any]:
    _require_device()
    try:
        out = await adb.install_apk(req.localPath)
    except adb.AdbError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"output": out}
