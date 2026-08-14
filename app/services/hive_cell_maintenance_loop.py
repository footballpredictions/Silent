"""Фоновый цикл: cell-agent + manifest на сотах (каждые ~10 с)."""
from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.services.hive_incidents import push_incident

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

                    vpnbase_stats = await push_vpnbase_export(db)
                    if vpnbase_stats.get("ok"):
                        logger.info(
                            "vpnbase export: v%s → %s",
                            vpnbase_stats.get("version"),
                            vpnbase_stats.get("repo"),
                        )
                    elif not vpnbase_stats.get("skipped"):
                        logger.warning("vpnbase export failed: %s", vpnbase_stats)
                        push_incident(
                            source="hive.maintenance",
                            severity="warning",
                            message="vpnbase export failed",
                            details=str(vpnbase_stats)[:400],
                        )
        except Exception as e:
            logger.warning("Hive cell maintenance cycle failed: %s", e)
            push_incident(
                source="hive.maintenance",
                severity="error",
                message=f"Hive maintenance cycle failed: {e}",
            )
        await asyncio.sleep(interval)


def start_hive_cell_maintenance_loop() -> asyncio.Task:
    return asyncio.create_task(hive_cell_maintenance_loop())
