"""Фоновый цикл балансировки Улья и sync manifest на соты."""
from __future__ import annotations

import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def hive_rebalance_loop() -> None:
    interval = max(15, int(settings.HIVE_REBALANCE_INTERVAL_SEC))
    await asyncio.sleep(25)
    logger.info("Hive rebalance loop started (every %ss)", interval)
    while True:
        try:
            from app.database import AsyncSessionLocal
            from app.services.hive_cell_sync import sync_all_cell_manifests
            from app.services.hive_service import rebalance_overloaded_cells

            async with AsyncSessionLocal() as db:
                stats = await rebalance_overloaded_cells(db)
                if stats.get("moved"):
                    logger.info(
                        "Hive rebalance: moved=%s blocked=%s hardware=%s return=%s",
                        stats.get("moved"),
                        stats.get("blocked"),
                        stats.get("hardware"),
                        stats.get("returned"),
                    )
        except Exception as e:
            logger.warning("Hive rebalance cycle failed: %s", e)
        await asyncio.sleep(interval)


def start_hive_rebalance_loop() -> asyncio.Task:
    return asyncio.create_task(hive_rebalance_loop())
