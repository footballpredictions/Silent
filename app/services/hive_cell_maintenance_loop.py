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
            from app.services.vpn_service import clear_stale_online_status

            async with AsyncSessionLocal() as db:
                # Авто-чистка "залипшего online", если клиент исчез без корректного disconnect.
                stale_off = await clear_stale_online_status(db)
                if stale_off:
                    logger.info("Hive stale-online cleanup: %s device(s) marked offline", stale_off)
                from app.services.vpn_kick import kick_connected_without_subscription

                kicked = await kick_connected_without_subscription(db)
                if kicked:
                    logger.info("Hive vpn kick: %s connected device(s) without subscription", kicked)
                from app.services.vpn_kick import refresh_peer_snapshots

                await refresh_peer_snapshots(db)
                from app.services.wg_peer_gc import gc_stale_queen_peers

                gc = await gc_stale_queen_peers(db)
                if gc.get("removed"):
                    logger.info("Hive wg peer gc: %s", gc)
            async with AsyncSessionLocal() as db:
                agent_stats = await auto_upgrade_cell_agents(db)
                if agent_stats.get("upgraded"):
                    logger.info("Hive cell-agent sync: upgraded %s cell(s)", agent_stats["upgraded"])
                if settings.HIVE_CELL_MANIFEST_SYNC_ENABLED:
                    await sync_all_cell_manifests(db)
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
