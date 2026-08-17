"""File transfer between the host and the emulated device.

The emulator itself is isolated — it cannot see the host filesystem. These
endpoints are the deliberate bridge, and every device path is validated to stay
inside user-writable storage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import adb, emulator

router = APIRouter(prefix="/api/files", tags=["files"])


class PushRequest(BaseModel):
    localPath: str
    devicePath: str = "/sdcard/Download"


class PullRequest(BaseModel):
    devicePath: str
    localPath: str


def _require_device() -> None:
    if emulator.manager.device is None:
        raise HTTPException(409, "No device is running.")
    if not adb.available():
        raise HTTPException(
            409,
            "platform-tools is not installed. Install it from the Packages tab to "
            "enable file transfer.",
        )


@router.get("/device")
async def list_device(path: str = "/sdcard") -> dict[str, Any]:
    _require_device()
    try:
        return await adb.list_dir(path)
    except adb.AdbError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/host")
async def list_host(path: str | None = None) -> dict[str, Any]:
    """Browse the host filesystem so the UI can pick a file to send."""
    target = Path(path).expanduser() if path else Path.home()
    if not target.exists():
        raise HTTPException(404, f"No such folder: {target}")
    if not target.is_dir():
        raise HTTPException(400, f"Not a folder: {target}")

    entries: list[dict[str, Any]] = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                is_dir = child.is_dir()
                entries.append({
                    "name": child.name,
                    "isDir": is_dir,
                    "size": 0 if is_dir else child.stat().st_size,
                    "path": str(child),
                })
            except OSError:
                continue
    except PermissionError as exc:
        raise HTTPException(403, f"Permission denied: {target}") from exc

    return {
        "path": str(target),
        "parent": str(target.parent) if target.parent != target else None,
        "entries": entries[:2000],
    }


@router.post("/push")
async def push(req: PushRequest) -> dict[str, Any]:
    """Host -> device."""
    _require_device()
    try:
        out = await adb.push(req.localPath, req.devicePath)
    except adb.AdbError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"output": out}


@router.post("/pull")
async def pull(req: PullRequest) -> dict[str, Any]:
    """Device -> host."""
    _require_device()
    try:
        out = await adb.pull(req.devicePath, req.localPath)
    except adb.AdbError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"output": out}
