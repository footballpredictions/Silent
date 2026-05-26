"""
24/7 VK Tunnel Monitor — runs only when AI agent is connected in admin panel.
"""
import asyncio
import logging
from datetime import datetime

from app.database import AsyncSessionLocal
from ai.vk_manager import VkManager

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300
STARTUP_DELAY_SECONDS = 10


async def monitor_loop():
    logger.info("VK Tunnel Monitor starting...")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)

    consecutive_failures = 0

    while True:
        manager = None
        try:
            async with AsyncSessionLocal() as db:
                from app.services.vk_agent_auth import is_agent_enabled
                if not await is_agent_enabled(db):
                    logger.debug("VK agent disabled — skip monitor cycle")
                else:
                    manager = VkManager(db)
                    if not manager._token:
                        auth_ok = await manager.authenticate()
                        if not auth_ok:
                            logger.error("VK auth failed, will retry in 60s")
                            await asyncio.sleep(60)
                            continue
                    await manager.check_and_heal()
                    consecutive_failures = 0
                    logger.debug("VK hash check completed at %s", datetime.utcnow().isoformat())

        except Exception as e:
            consecutive_failures += 1
            logger.error("Monitor error (attempt %s): %s", consecutive_failures, e)
            if consecutive_failures >= 5:
                logger.critical("5 consecutive monitor failures, sleeping 10 min")
                await asyncio.sleep(600)
                consecutive_failures = 0
        finally:
            if manager:
                await manager.close()

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_monitor_background():
    loop = asyncio.get_event_loop()
    task = loop.create_task(monitor_loop())
    logger.info("VK tunnel monitor started as background task")
    return task
