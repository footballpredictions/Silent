"""Small reserve of verified, unassigned VK call links for first connections."""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ai.vk_manager import MAX_HASHES
from app.models import AppSetting, User, VkHash

SETTING = "vk_issuer_hash_reserve"
CAPACITY = 2 * MAX_HASHES
MAX_AGE = timedelta(hours=24)


def _available(raw: str | None) -> list[list[str]]:
    try:
        records = json.loads(raw or "[]")
    except ValueError:
        return []
    if not isinstance(records, list):
        return []
    cutoff = datetime.now(timezone.utc) - MAX_AGE
    ready = []
    for item in records:
        if not isinstance(item, list) or len(item) != 2 or not all(isinstance(x, str) for x in item):
            continue
        try:
            verified = datetime.fromisoformat(item[1])
        except ValueError:
            continue
        if verified.tzinfo is None:
            verified = verified.replace(tzinfo=timezone.utc)
        if item[0] and verified >= cutoff:
            ready.append(item)
    return ready


async def enabled(db) -> bool:
    return await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING)) is not None


async def _locked_reserve(db):
    return await db.scalar(select(AppSetting).where(AppSetting.key == SETTING)
                           .with_for_update().execution_options(populate_existing=True))


async def claim_ready_hashes(db, user_id) -> int:
    from ai.vk_manager import VkManager

    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING))
    if not _available(raw):
        return 0
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())
    occupied = set(await db.scalars(select(VkHash.slot_index).where(
        VkHash.user_id == user_id, VkHash.is_active.is_(True),
    )))
    missing = [slot for slot in range(MAX_HASHES) if slot not in occupied]
    if not missing:
        await db.commit()
        return 0
    reserve = await _locked_reserve(db)
    ready = _available(reserve.value if reserve else None)
    if not ready:
        await db.commit()
        return 0
    claimed = min(len(ready), len(missing))
    manager = VkManager(db)
    for slot, (hash_val, _) in zip(missing, ready[:claimed]):
        await manager.upsert_hash_slot(slot, hash_val, f"https://vk.com/call/join/{hash_val}",
                                       user_id=user_id, commit=False)
    reserve.value = json.dumps(ready[claimed:])
    await db.commit()
    return claimed


async def needs_refill(db) -> bool:
    from app.services.vk_agent_auth import _setting
    from app.services.vk_agent_runtime import now_utc, timestamp

    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING))
    if raw is None or len(_available(raw)) >= CAPACITY:
        return False
    pause_until = timestamp(await _setting(db, "vk_hash_probe_until"))
    return not pause_until or pause_until <= now_utc()


async def refill_one(db, manager) -> bool:
    from app.services.vk_agent_runtime import now_utc

    if not await needs_refill(db):
        return False
    hash_val = await manager.create_call(pilot_leave=True)
    if not hash_val:
        return False
    reserve = await _locked_reserve(db)
    if reserve is None:
        return False
    ready = _available(reserve.value)
    if len(ready) >= CAPACITY or any(item[0] == hash_val for item in ready):
        await db.commit()
        return False
    ready.append([hash_val, now_utc().isoformat()])
    reserve.value = json.dumps(ready)
    await db.commit()
    return True
