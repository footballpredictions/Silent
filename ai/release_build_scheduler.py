"""Daily 00:00 MSK OTA rebuild (new bootstrap hash, same app version)."""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")
STARTUP_DELAY_SECONDS = 45
CHECK_INTERVAL_SECONDS = 60


async def scheduler_loop() -> None:
    logger.info("Release build scheduler starting (00:00 MSK)")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)

    while True:
        try:
            now = datetime.now(MSK)
            if now.hour == 0 and now.minute < 2:
                async with AsyncSessionLocal() as db:
                    from app.services.vk_agent_auth import is_agent_enabled
                    from app.services.build_agent_service import run_nightly_release_builds, _setting, _set_setting

                    if await is_agent_enabled(db):
                        today = now.strftime("%Y-%m-%d")
                        last = await _setting(db, "build_agent_nightly_date")
                        if last != today:
                            logger.info("Running nightly OTA build for %s", today)
                            await run_nightly_release_builds(db)
                            await _set_setting(db, "build_agent_nightly_date", today)
        except Exception as e:
            logger.exception("Release build scheduler error: %s", e)

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_release_build_scheduler():
    loop = asyncio.get_event_loop()
    task = loop.create_task(scheduler_loop())
    logger.info("Release build scheduler started")
    return task
