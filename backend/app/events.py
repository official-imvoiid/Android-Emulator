"""Tiny in-process pub/sub so long jobs can stream progress to WebSocket clients."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any


class EventBus:
    def __init__(self, history: int = 400) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history)
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subscribers.add(q)
            # Replay recent history so a client that connects late isn't blind.
            for event in list(self._history):
                q.put_nowait(event)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    def publish(self, kind: str, **payload: Any) -> None:
        event = {"kind": kind, "ts": time.time(), **payload}
        if kind != "progress":
            # Progress is high-frequency and replaying it is noise; keep the rest.
            self._history.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def log(self, message: str, level: str = "info") -> None:
        self.publish("log", level=level, message=message)


bus = EventBus()
