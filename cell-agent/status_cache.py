"""Один снимок /v1/status на пачку одновременных опросов Улья."""
from __future__ import annotations

import asyncio
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class StatusCache:
    def __init__(self, ttl: float = 2.0) -> None:
        self.ttl = ttl
        self._at = 0.0
        self._body: T | None = None
        self._inflight: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def _fresh(self, now: float) -> bool:
        return self._body is not None and (now - self._at) < self.ttl

    async def get(self, collect: Callable[[], T]) -> T:
        now = time.monotonic()
        if self._fresh(now):
            return self._body  # type: ignore[return-value]
        async with self._lock:
            now = time.monotonic()
            if self._fresh(now):
                return self._body  # type: ignore[return-value]
            if self._inflight is None or self._inflight.done():
                self._inflight = asyncio.create_task(self._run(collect))
            task = self._inflight
        return await task

    async def _run(self, collect: Callable[[], T]) -> T:
        body = await asyncio.to_thread(collect)
        self._body = body
        self._at = time.monotonic()
        return body
