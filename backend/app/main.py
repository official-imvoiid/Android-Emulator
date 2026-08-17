"""Android Emulator Hub — backend entry point.

Run with:  uvicorn app.main:app --port 8765
"""
from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import settings
from .api import device, files, sdk, system
from .core import adb, avd, emulator
from .events import bus

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    removed = avd.cleanup_stale_temp_sessions()
    if removed:
        bus.log(f"Cleaned up {removed} orphaned temporary session(s).")
    bus.log(f"Isolated SDK root: {settings.SDK_ROOT}")
    yield
    # Never leave a device or an adb server running after the app closes.
    with contextlib.suppress(Exception):
        await emulator.manager.stop()
    with contextlib.suppress(Exception):
        await adb.kill_server()
    with contextlib.suppress(Exception):
        await sdk.shutdown_client()


app = FastAPI(
    title="Android Emulator Hub",
    version="1.0.0",
    description=(
        "Pick RAM, storage, CPU, graphics and persistence, choose an Android version, "
        "and boot a Play Store device. The SDK catalog is read from Google's live "
        "manifests at runtime, so new Android releases appear with no update."
    ),
    lifespan=lifespan,
)

# The React dev server runs on a different port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(sdk.router)
app.include_router(device.router)
app.include_router(files.router)


@app.get("/api/health")
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "sdkRoot": str(settings.SDK_ROOT),
        "emulatorInstalled": settings.emulator_binary().exists(),
        "adbInstalled": settings.adb_binary().exists(),
        "deviceRunning": emulator.manager.device is not None,
    }


@app.websocket("/ws")
async def websocket_events(ws: WebSocket) -> None:
    """Streams logs, download progress and device state changes."""
    await ws.accept()
    queue = await bus.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=25.0)
            except asyncio.TimeoutError:
                await ws.send_json({"kind": "ping"})
                continue
            await ws.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await bus.unsubscribe(queue)


# ------------------------------------------------------- built frontend (prod)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def dev_hint() -> dict[str, str]:
        return {
            "message": "Backend is running. Start the React dev server with `npm run dev` "
                       "in ./frontend, then open http://localhost:5173",
            "docs": "/docs",
        }
