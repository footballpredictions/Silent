"""Лидер-выбор для фоновых агентов.

`uvicorn --workers N` поднимает lifespan в каждом воркере, поэтому без этого
каждый агент (VK, olcrtc room agent, Улей, proxy health) крутится N раз:
дублируются провижининг комнат, SSH-сессии и потребление памяти.

Лидер держит postgres advisory lock на своём соединении: как только воркер
падает, соединение закрывается, lock освобождается и лидером становится другой.
"""
from __future__ import annotations

import asyncio
import logging
import os
import zlib
from typing import Awaitable, Callable

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

RETRY_SECONDS = 30
KEEPALIVE_SECONDS = 20


def _lock_key(name: str) -> int:
    """Стабильный int64 из имени (advisory lock принимает bigint)."""
    return zlib.crc32(name.encode("utf-8")) & 0x7FFFFFFF


class LeaderLock:
    """Advisory lock, живущий столько же, сколько удерживаемое соединение."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.key = _lock_key(name)
        self._conn = None

    async def try_acquire(self) -> bool:
        if self._conn is not None:
            return True
        conn = await engine.connect()
        try:
            got = await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": self.key})
        except Exception:
            await conn.close()
            raise
        if not got:
            await conn.close()
            return False
        self._conn = conn
        return True

    async def still_held(self) -> bool:
        if self._conn is None:
            return False
        try:
            await self._conn.scalar(text("SELECT 1"))
            return True
        except Exception as e:
            logger.warning("leader lock %s: соединение потеряно (%s)", self.name, e)
            await self.release()
            return False

    async def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            await conn.close()
        except Exception:
            pass


LoopFactory = Callable[[], Awaitable[None]]


async def _supervise(name: str, factories: list[tuple[str, LoopFactory]]) -> None:
    lock = LeaderLock(name)
    started: list[asyncio.Task] = []
    try:
        while True:
            if not started:
                try:
                    if await lock.try_acquire():
                        for title, factory in factories:
                            started.append(asyncio.create_task(factory(), name=title))
                        logger.info(
                            "leader=%s pid=%s: запущено фоновых агентов %s",
                            name,
                            os.getpid(),
                            len(started),
                        )
                    else:
                        logger.info(
                            "leader=%s pid=%s: агенты уже ведёт другой воркер",
                            name,
                            os.getpid(),
                        )
                except Exception:
                    logger.exception("leader %s: не удалось взять lock", name)
                await asyncio.sleep(RETRY_SECONDS if not started else KEEPALIVE_SECONDS)
                continue

            await asyncio.sleep(KEEPALIVE_SECONDS)
            if not await lock.still_held():
                for task in started:
                    task.cancel()
                started.clear()
    except asyncio.CancelledError:
        for task in started:
            task.cancel()
        raise
    finally:
        await lock.release()


def start_when_leader(name: str, factories: list[tuple[str, LoopFactory]]) -> asyncio.Task:
    """Запустить набор фоновых циклов только в одном воркере."""
    return asyncio.create_task(_supervise(name, factories), name=f"leader:{name}")
