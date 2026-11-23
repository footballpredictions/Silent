"""VK issuer: consume persisted dead slots, periodically fill missing slots."""
import asyncio
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import distinct, func, or_, select
from app.database import AsyncSessionLocal
from app.models import User, VkHash
from app.services import vk_hash_reserve
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
    reserve_due = await vk_hash_reserve.needs_refill(db)
    if not full_fill:
        result = await db.execute(select(VkHash.user_id).where(
            VkHash.user_id.isnot(None), VkHash.slot_index >= 0, VkHash.slot_index < MAX_HASHES,
            or_(VkHash.is_active == False, VkHash.last_error_code == 1),  # noqa: E712
        ).distinct())
        user_ids = list(result.scalars().all())
        if await vk_hash_reserve.enabled(db):
            from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

            active_slots = select(func.count(distinct(VkHash.slot_index))).where(
                VkHash.user_id == User.id, VkHash.is_active.is_(True),
                VkHash.slot_index >= 0, VkHash.slot_index < MAX_HASHES,
            ).correlate(User).scalar_subquery()
            recent = await db.scalars(select(User.id).where(
                User.is_verified.is_(True), User.is_active.is_(True), User.email != BOOTSTRAP_USER_EMAIL,
                User.created_at >= datetime.utcnow() - timedelta(days=1), active_slots < MAX_HASHES,
            ).order_by(User.created_at).limit(4))
            user_ids = list(dict.fromkeys([*recent, *user_ids]))
        if not user_ids and not reserve_due:
            return
    manager = VkManager(db)
    try:
        if full_fill:
            message = await manager.fill_all_user_slots()
        else:
            async with agent_lease("issuer") as acquired:
                if not acquired:
                    return
                if user_ids and not await manager.authenticate(verify_calls=False):
                    await set_agent_run_log(db, "Ошибка авторизации VK: замена отложена", ok=False)
                    return "Ошибка авторизации VK: замена отложена"
                created = 0
                for uid in user_ids:
                    created += await manager.fill_user_empty_slots(uid)
                    if manager._flood_hit or manager._room_exit_failed:
                        break
                message = f"Очередь мёртвых хешей: +{created}, пользователей={len(user_ids)}"
        if reserve_due and not manager._flood_hit and not manager._room_exit_failed:
            async with agent_lease("issuer") as acquired:
                if acquired and await vk_hash_reserve.refill_one(db, manager):
                    logger.info("VK issuer: replenished one verified reserve hash")
        if manager._flood_hit and not (await is_flood_cooldown(db))[0]:
            await set_flood_cooldown(db, minutes=manager._flood_cooldown_minutes)
        if manager._room_exit_failed and not message.startswith("Ошибка"):
            message = f"Ошибка VK: {manager._last_auth_error}; {message}"
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
