"""Быстрый цикл пула olcrtc: освобождение слотов отключившихся клиентов.

Агент комнат ходит раз в 15 минут — этого мало: клиент, который выключил VPN,
держал бы слот до следующего цикла и остальным показывало бы «нет свободных
комнат». Здесь sticky без heartbeat снимаются раз в полминуты.
"""
from __future__ import annotations

import asyncio
import logging

from app.database import AsyncSessionLocal
from app.services.olcrtc_assign import reconcile_stale_online

logger = logging.getLogger(__name__)

POOL_RECONCILE_SECONDS = 30
STARTUP_DELAY_SECONDS = 15


async def olcrtc_pool_loop() -> None:
    logger.info("olcrtc pool reconcile loop starting…")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                freed = await reconcile_stale_online(db)
                if freed:
                    logger.info("olcrtc pool: освобождено слотов/комнат: %s", freed)
        except Exception:
            logger.exception("olcrtc pool reconcile error")
        await asyncio.sleep(POOL_RECONCILE_SECONDS)
