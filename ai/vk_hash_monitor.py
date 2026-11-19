"""Continuous anonymous join-link checker. Never creates calls."""
import asyncio
import logging

from app.database import AsyncSessionLocal
from ai.vk_manager import VkManager

logger = logging.getLogger(__name__)
STARTUP_DELAY_SECONDS = 20
BATCH_PAUSE_SECONDS = 5
ERROR_BACKOFF_SECONDS = 60


async def run_probe_cycle(db):
    from app.services.vk_agent_auth import is_agent_enabled
    if not await is_agent_enabled(db):
        return
    manager = VkManager(db)
    try:
        return await manager.probe_active_hashes()
    finally:
        await manager.close()


async def monitor_loop():
    logger.info("VK Hash Checker starting (continuous, anonymous preview only)")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        pause = BATCH_PAUSE_SECONDS
        try:
            async with AsyncSessionLocal() as db:
                result = await run_probe_cycle(db)
                if result:
                    logger.info("VK Hash Checker: %s", result)
                if not result or any(word in result for word in ("пауза", "пропуск", "занята")):
                    pause = ERROR_BACKOFF_SECONDS
        except Exception:
            logger.exception("VK Hash Checker cycle failed")
            pause = ERROR_BACKOFF_SECONDS
        await asyncio.sleep(pause)
