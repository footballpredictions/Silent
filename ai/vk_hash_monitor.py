"""Continuous anonymous join-link checker. Never creates calls."""
import asyncio
import logging
import aiohttp

from app.database import AsyncSessionLocal
from ai.vk_manager import VkManager
from ai.vk_hash_liveness import JoinHashProber
from app.services.vk_agent_auth import VK_USER_AGENT

logger = logging.getLogger(__name__)
STARTUP_DELAY_SECONDS = 20
BATCH_PAUSE_SECONDS = 5
ERROR_BACKOFF_SECONDS = 60


async def run_probe_cycle(db, *, prober=None):
    from app.services.vk_agent_runtime import tracked_cycle
    return await tracked_cycle(db, "checker", lambda: _probe(db, prober), delay=BATCH_PAUSE_SECONDS)


async def _probe(db, prober=None):
    manager = VkManager(db)
    manager._probe_client = prober
    try:
        return await manager.probe_active_hashes()
    finally:
        await manager.close()


async def monitor_loop():
    logger.info("VK Hash Checker starting (continuous, anonymous preview only)")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    async with aiohttp.ClientSession(headers={"User-Agent": VK_USER_AGENT}, timeout=aiohttp.ClientTimeout(total=30)) as session:
        await _continuous(JoinHashProber(session))


async def _continuous(prober):
    while True:
        pause = BATCH_PAUSE_SECONDS
        try:
            async with AsyncSessionLocal() as db:
                result = await run_probe_cycle(db, prober=prober)
                if result:
                    logger.info("VK Hash Checker: %s", result)
                if not result or any(word in result for word in ("пауза", "пропуск", "занята")):
                    pause = ERROR_BACKOFF_SECONDS
        except Exception:
            logger.exception("VK Hash Checker cycle failed")
            pause = ERROR_BACKOFF_SECONDS
        await asyncio.sleep(pause)
