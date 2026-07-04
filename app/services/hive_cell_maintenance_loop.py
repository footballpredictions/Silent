"""Фоновый цикл: cell-agent + manifest на сотах (каждые ~10 с)."""
from __future__ import annotations

import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)


async def hive_cell_maintenance_loop() -> None:
    interval = max(10, int(settings.HIVE_CELL_MAINTENANCE_INTERVAL_SEC))
    await asyncio.sleep(12)
    logger.info("Hive cell maintenance loop started (every %ss)", interval)
    while True:
        try:
            from app.database import AsyncSessionLocal
            from app.services.hive_cell_agent_auto import auto_upgrade_cell_agents
            from app.services.hive_cell_sync import sync_all_cell_manifests

            async with AsyncSessionLocal() as db:
                agent_stats = await auto_upgrade_cell_agents(db)
                if agent_stats.get("upgraded"):
                    logger.info("Hive cell-agent sync: upgraded %s cell(s)", agent_stats["upgraded"])
                if settings.HIVE_CELL_MANIFEST_SYNC_ENABLED:
                    await sync_all_cell_manifests(db)
                if settings.VPNBASE_GIT_ENABLED:
                    from app.services.hive_vpnbase_export import push_vpnbase_export

                    await push_vpnbase_export(db)
        except Exception as e:
            logger.warning("Hive cell maintenance cycle failed: %s", e)
        await asyncio.sleep(interval)


def start_hive_cell_maintenance_loop() -> asyncio.Task:
    return asyncio.create_task(hive_cell_maintenance_loop())
