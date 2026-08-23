"""olcrtc2 room agent — выключен.

Продукт на WDTT. Старый цикл грел Telemost/WB комнаты на сотах и ел CPU.
Даже если в app_settings снова поставить enabled — цикл не стартует.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

INTERVAL_SEC = 45


async def monitor_loop() -> None:
    logger.info("olcrtc2 room agent disabled (VK/WDTT only)")


async def agent_status(db) -> dict[str, Any]:
    from app.services.olcrtc2_assign import pool_stats
    from app.services.olcrtc2_settings import load_olcrtc2_settings

    settings = await load_olcrtc2_settings(db)
    stats = await pool_stats(db)
    return {
        "product_on": False,
        "agent_on": False,
        "session_mode": True,
        "interval_sec": INTERVAL_SEC,
        "warm_pool_per_dt": 0,
        "warm_pool_by_provider": {"telemost": 0, "wbstream": 0},
        "target_online": 0,
        "pool": stats,
        "cell_ip": settings.get("cell_ip"),
        "cells": settings.get("cells") or {},
        "providers_enabled": [],
        "provider": settings.get("provider"),
        "disabled_reason": "VK/WDTT only",
    }
