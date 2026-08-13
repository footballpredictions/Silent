"""olcrtc2 room agent — warm pool + prune; assign берёт готовые комнаты (~1с)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

INTERVAL_SEC = 45
STARTUP_DELAY_SECONDS = 15
_scale_defaults_done = False


async def monitor_loop() -> None:
    from app.database import AsyncSessionLocal
    from app.services.olcrtc2_assign import ensure_warm_pool, prune_stale_sessions
    from app.services.olcrtc2_settings import load_olcrtc2_settings

    logger.info("olcrtc2 room agent monitor starting (interval=%ss)…", INTERVAL_SEC)
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    global _scale_defaults_done
    while True:
        try:
            async with AsyncSessionLocal() as db:
                settings = await load_olcrtc2_settings(db)
                if not _scale_defaults_done:
                    from app.services.olcrtc2_settings import save_olcrtc2_settings

                    patch: dict[str, Any] = {}
                    if int(settings.get("target_online") or 0) < 150:
                        patch["target_online"] = 150
                    if int(settings.get("warm_pool_per_dt") or 0) < 12:
                        patch["warm_pool_per_dt"] = 20
                    if patch:
                        settings = await save_olcrtc2_settings(db, patch)
                        logger.info("olcrtc2 scale defaults: %s", patch)
                    _scale_defaults_done = True
                if settings.get("enabled") and settings.get("agent_enabled"):
                    warm = await ensure_warm_pool(db)
                    if warm.get("created"):
                        logger.info("olcrtc2 agent warm: %s", warm)
                    stats = await prune_stale_sessions(db)
                    if stats.get("torn_down"):
                        logger.info("olcrtc2 agent prune: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("olcrtc2 agent loop")
        await asyncio.sleep(INTERVAL_SEC)


async def agent_status(db) -> dict[str, Any]:
    from app.services.olcrtc2_assign import pool_stats
    from app.services.olcrtc2_settings import load_olcrtc2_settings

    settings = await load_olcrtc2_settings(db)
    stats = await pool_stats(db)
    return {
        # НЕ звать keys enabled/agent_enabled — админка мержит JSON и может затереть флаги продукта
        "product_on": bool(settings.get("enabled")),
        "agent_on": bool(settings.get("agent_enabled")),
        "session_mode": True,
        "interval_sec": INTERVAL_SEC,
        "warm_pool_per_dt": int(settings.get("warm_pool_per_dt") or 20),
        "target_online": int(settings.get("target_online") or 150),
        "pool": stats,
        "cell_ip": settings.get("cell_ip"),
        "cells": settings.get("cells") or {},
        "providers_enabled": settings.get("providers_enabled") or [],
        "provider": settings.get("provider"),
    }
