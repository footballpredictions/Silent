"""
24/7 VK Tunnel Monitor — background asyncio task that:
1. Every 5 minutes checks if all VK hashes are alive
2. If any hash is dead: tries reconnect (soft heal)
3. If reconnect fails: recreates all 3 hashes from scratch
4. On startup: creates hashes if none exist
"""
import asyncio
import logging
from datetime import datetime

from app.database import AsyncSessionLocal
from ai.vk_manager import VkManager

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300  # 5 minutes
STARTUP_DELAY_SECONDS = 10


async def monitor_loop():
    """Main monitoring coroutine. Runs forever."""
    logger.info("VK Tunnel Monitor starting...")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)

    manager = None
    consecutive_failures = 0

    while True:
        try:
            async with AsyncSessionLocal() as db:
                manager = VkManager(db)

                # Ensure authenticated
                if not manager._token:
                    auth_ok = await manager.authenticate()
                    if not auth_ok:
                        logger.error("VK auth failed, will retry in 60s")
                        await asyncio.sleep(60)
                        continue

                await manager.check_and_heal()
                consecutive_failures = 0
                logger.debug(f"VK hash check completed at {datetime.utcnow().isoformat()}")

        except Exception as e:
            consecutive_failures += 1
            logger.error(f"Monitor error (attempt {consecutive_failures}): {e}")
            if consecutive_failures >= 5:
                logger.critical("5 consecutive monitor failures, sleeping 10 min")
                await asyncio.sleep(600)
                consecutive_failures = 0
        finally:
            if manager:
                await manager.close()
                manager = None

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_monitor_background():
    """Call this from FastAPI lifespan to start the monitor task."""
    loop = asyncio.get_event_loop()
    task = loop.create_task(monitor_loop())
    logger.info("VK tunnel monitor started as background task")
    return task
