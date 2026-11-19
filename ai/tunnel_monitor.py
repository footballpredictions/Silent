"""VK issuer: consume persisted dead slots, periodically fill missing slots."""
import asyncio
import logging
import time

from sqlalchemy import or_, select
from app.database import AsyncSessionLocal
from app.models import VkHash
from ai.vk_manager import VkManager, MAX_HASHES

logger = logging.getLogger(__name__)
CHECK_INTERVAL_SECONDS = 900
QUEUE_POLL_SECONDS = 30
STARTUP_DELAY_SECONDS = 10


async def run_heal_cycle(db, *, full_fill: bool):
    from app.services.vk_agent_runtime import tracked_cycle
    return await tracked_cycle(db, "issuer", lambda: _heal(db, full_fill=full_fill), delay=QUEUE_POLL_SECONDS)


async def _heal(db, *, full_fill: bool):
    from app.services.vk_agent_auth import set_agent_run_log, set_flood_cooldown, is_flood_cooldown
    from ai.vk_agent_lock import agent_lease

    flood, _ = await is_flood_cooldown(db)
    if flood:
        return
    user_ids = []
    if not full_fill:
        result = await db.execute(select(VkHash.user_id).where(
            VkHash.user_id.isnot(None), VkHash.slot_index >= 0, VkHash.slot_index < MAX_HASHES,
            or_(VkHash.is_active == False, VkHash.last_error_code == 1),  # noqa: E712
        ).distinct())
        user_ids = list(result.scalars().all())
        if not user_ids:
            return
    manager = VkManager(db)
    try:
        if full_fill:
            message = await manager.fill_all_user_slots()
        else:
            async with agent_lease("issuer") as acquired:
                if not acquired:
                    return
                if not await manager.authenticate(verify_calls=False):
                    await set_agent_run_log(db, "Ошибка авторизации VK: замена отложена", ok=False)
                    return "Ошибка авторизации VK: замена отложена"
                created = 0
                for uid in user_ids:
                    created += await manager.fill_user_empty_slots(uid)
                    if manager._flood_hit:
                        await set_flood_cooldown(db, minutes=45)
                        break
                message = f"Очередь мёртвых хешей: +{created}, пользователей={len(user_ids)}"
        await set_agent_run_log(db, message, ok=not manager._flood_hit and not message.startswith("Ошибка"))
        return message
    finally:
        await manager.close()


async def monitor_loop():
    logger.info("VK Tunnel Monitor starting (issuer, persisted dead-slot queue)")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    next_full = 0.0
    while True:
        try:
            full_fill = time.monotonic() >= next_full
            async with AsyncSessionLocal() as db:
                await run_heal_cycle(db, full_fill=full_fill)
            if full_fill:
                next_full = time.monotonic() + CHECK_INTERVAL_SECONDS
        except Exception:
            logger.exception("VK issuer cycle failed")
        await asyncio.sleep(QUEUE_POLL_SECONDS)


def start_monitor_background():
    return asyncio.get_running_loop().create_task(monitor_loop())
