"""Tracking which SDK packages are already on disk.

We write our own marker rather than imitating sdkmanager's package.xml, so this
tool's SDK root is unambiguously ours and can never be confused with (or corrupt)
a real Android Studio installation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .. import settings

MARKER = ".emuhub-package.json"


def _marker_path(package_path: str) -> Path:
    return settings.SDK_ROOT.joinpath(*package_path.split(";")) / MARKER


def record(package_path: str, revision: str, checksum: str, size: int) -> None:
    target = _marker_path(package_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "path": package_path,
                "revision": revision,
                "checksum": checksum,
                "size": size,
                "installed_at": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def info(package_path: str) -> dict[str, Any] | None:
    marker = _marker_path(package_path)
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def is_installed(package_path: str, revision: str | None = None) -> bool:
    data = info(package_path)
    if not data:
        return False
    if revision is not None and data.get("revision") != revision:
        return False  # a newer revision was published; treat as upgradable
    return True


def list_installed() -> list[dict[str, Any]]:
    root = settings.SDK_ROOT
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for marker in root.rglob(MARKER):
        try:
            out.append(json.loads(marker.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    out.sort(key=lambda d: d.get("path", ""))
    return out


def disk_usage_mb(package_path: str) -> int:
    directory = settings.SDK_ROOT.joinpath(*package_path.split(";"))
    if not directory.exists():
        return 0
    total = 0
    for f in directory.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total // (1024 * 1024)
