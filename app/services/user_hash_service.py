"""Per-user VK call hashes: bootstrap (user) + 4 server slots."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ai.vk_manager import MAX_HASHES
from app.models import User, VkHash, Device
from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

logger = logging.getLogger(__name__)

# Должно совпадать с ai.vk_manager.MAX_HASHES и клиентами (Android/PC MAX_HASHES=4).
MAX_SERVER_SLOTS = MAX_HASHES
LIBCLIENT_MAX_WORKERS = 108
WORKERS_PER_HASH = 27


def recommended_stream_count(active_server_hash_count: int) -> int:
    """Recommended libclient -n: active server hashes × 27 (max 108)."""
    capped = min(max(active_server_hash_count, 1), MAX_HASHES)
    return min(capped * WORKERS_PER_HASH, LIBCLIENT_MAX_WORKERS)


def extract_call_hash(value: str) -> str | None:
    import re

    s = (value or "").strip()
    if not s:
        return None
    s = s.split("?")[0].split("#")[0].strip().rstrip("/")
    m = re.search(r"/join/([A-Za-z0-9_\-]+)", s, re.I)
    if m:
        return m.group(1).rstrip("/")
    m2 = re.search(r"join/([A-Za-z0-9_\-]+)", s, re.I)
    if m2:
        return m2.group(1).rstrip("/")
    bare = re.sub(r"^https?://", "", s, flags=re.I)
    bare = bare.removeprefix("www.").strip()
    if re.match(r"^[A-Za-z0-9_\-]{6,128}$", bare):
        return bare
    return None


async def get_server_hashes_for_user(db: AsyncSession, user: User) -> list[str]:
    """Active server hashes only — for libclient -vk (bootstrap excluded)."""
    out: list[str] = []
    result = await db.execute(
        select(VkHash.hash_value)
        .where(VkHash.user_id == user.id, VkHash.is_active == True)
        .order_by(VkHash.slot_index)
    )
    for (h,) in result.fetchall():
        h = (h or "").strip()
        if h and h not in out:
            out.append(h)
    return out[:MAX_SERVER_SLOTS]


async def get_vpn_hashes_for_user(db: AsyncSession, user: User) -> list[str]:
    """User bootstrap + up to 4 active server hashes (deduped)."""
    out: list[str] = []
    boot = (user.bootstrap_hash or "").strip()
    if boot:
        out.append(boot)
    for h in await get_server_hashes_for_user(db, user):
        if h not in out:
            out.append(h)
    return out


async def get_hash_items_for_user(db: AsyncSession, user: User) -> list[dict]:
    """Detailed hash list for client UI: bootstrap + server slots with status."""
    items: list[dict] = []
    boot = (user.bootstrap_hash or "").strip()
    if boot:
        items.append(
            {
                "hash": boot,
                "label": "Bootstrap",
                "source": "bootstrap",
                "slot_index": None,
                "is_active": True,
                "status": "active",
            }
        )

    for slot in range(MAX_SERVER_SLOTS):
        result = await db.execute(
            select(VkHash)
            .where(VkHash.user_id == user.id, VkHash.slot_index == slot)
            .order_by(VkHash.is_active.desc(), VkHash.updated_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not row:
            continue
        h = (row.hash_value or "").strip()
        if not h:
            continue
        active = bool(row.is_active)
        items.append(
            {
                "hash": h,
                "label": f"Сервер #{slot}",
                "source": "server",
                "slot_index": slot,
                "is_active": active,
                "status": "active" if active else "expired",
            }
        )
    return items


async def count_active_server_hashes(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Число занятых слотов 0–3 (не строк в БД — дубликаты не считаем)."""
    result = await db.execute(
        select(VkHash.slot_index).where(
            VkHash.user_id == user_id,
            VkHash.is_active == True,
        )
    )
    slots = {row[0] for row in result.fetchall() if 0 <= row[0] < MAX_SERVER_SLOTS}
    return len(slots)


async def dedupe_user_hash_slots(db: AsyncSession, user_id: uuid.UUID) -> int:
    """
    Один активный хеш на слот 0–3. Лишние дубликаты (часто slot=0) удаляем.
    Оставляем запись с меньшим fail_count, при равенстве — более новую.
    """
    from collections import defaultdict

    result = await db.execute(
        select(VkHash).where(VkHash.user_id == user_id, VkHash.is_active == True)
    )
    rows = list(result.scalars().all())
    if not rows:
        return 0

    by_slot: dict[int, list[VkHash]] = defaultdict(list)
    for h in rows:
        by_slot[h.slot_index].append(h)

    removed = 0
    for slot, group in by_slot.items():
        if slot < 0 or slot >= MAX_SERVER_SLOTS:
            for h in group:
                await db.delete(h)
                removed += 1
            continue
        group.sort(
            key=lambda x: (
                int(x.fail_count or 0),
                -(x.updated_at.timestamp() if x.updated_at else 0),
            )
        )
        for h in group[1:]:
            await db.delete(h)
            removed += 1

    if removed:
        await db.commit()
        logger.info("dedupe user %s: removed %s duplicate/invalid hash rows", user_id, removed)
    return removed


async def dedupe_all_user_hash_slots(db: AsyncSession) -> int:
    total = 0
    for uid in await list_users_for_monitor(db):
        total += await dedupe_user_hash_slots(db, uid)
    return total


async def set_user_bootstrap_hash(db: AsyncSession, user: User, raw: str) -> str:
    h = extract_call_hash(raw)
    if not h:
        raise ValueError("Неверный формат хеша или ссылки vk.com/call/join/…")
    user.bootstrap_hash = h
    await db.commit()
    await db.refresh(user)
    return h


async def cleanup_bootstrap_devices(db: AsyncSession, device_fingerprint: str) -> int:
    """Remove pre-login devices from synthetic bootstrap user (fixes duplicate in admin)."""
    fp = device_fingerprint.strip()
    if not fp:
        return 0
    boot_fp = f"boot:{fp}"
    result = await db.execute(select(User).where(User.email == BOOTSTRAP_USER_EMAIL))
    boot_user = result.scalar_one_or_none()
    if not boot_user:
        return 0
    del_result = await db.execute(
        delete(Device).where(
            Device.user_id == boot_user.id,
            Device.device_fingerprint == boot_fp,
        )
    )
    await db.commit()
    return del_result.rowcount or 0


async def ensure_user_server_hashes(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Create missing server slots (0–3) via AI agent when enabled."""
    from app.services.vk_agent_auth import is_agent_enabled
    from ai.vk_manager import VkManager

    if not await is_agent_enabled(db):
        return 0

    active = await count_active_server_hashes(db, user_id)
    if active >= MAX_SERVER_SLOTS:
        return 0

    manager = VkManager(db)
    created = 0
    try:
        ok, err = await manager.ensure_authenticated()
        if not ok:
            logger.warning("ensure_user_server_hashes: auth failed: %s", err)
            return 0
        for slot in range(MAX_SERVER_SLOTS):
            exists = await db.execute(
                select(VkHash.id).where(
                    VkHash.user_id == user_id,
                    VkHash.slot_index == slot,
                    VkHash.is_active == True,
                )
            )
            if exists.scalar_one_or_none():
                continue
            hash_val, msg = await manager.create_hash_for_user_slot(user_id, slot)
            if hash_val:
                created += 1
            else:
                logger.warning("slot %s for user %s: %s", slot, user_id, msg)
    finally:
        await manager.close()
    return created


async def request_hash_refresh(db: AsyncSession, user: User) -> tuple[bool, str]:
    """Client asks for new server hashes when slots are empty."""
    active = await count_active_server_hashes(db, user.id)
    if active >= MAX_SERVER_SLOTS:
        return True, "Хеши в норме"
    created = await ensure_user_server_hashes(db, user.id)
    if created > 0:
        return True, f"Добавлено хешей: {created}"
    if active == 0 and not user.bootstrap_hash:
        return False, "Нет bootstrap-хеша. Введите свой хеш звонка VK."
    return True, "Запрос принят. Админ может добавить хеши вручную или включить AI-агента."


async def list_users_for_monitor(db: AsyncSession) -> list[uuid.UUID]:
    """Все пользователи кроме bootstrap — агент заполняет слоты 0–3."""
    result = await db.execute(
        select(User.id).where(User.email != BOOTSTRAP_USER_EMAIL)
    )
    return [row[0] for row in result.fetchall()]


FAIL_COUNT_DEACTIVATE = 5


def _hash_matches(hint: str, full: str) -> bool:
    hint = (hint or "").strip()
    full = (full or "").strip()
    if not hint or not full:
        return False
    if hint == full:
        return True
    if len(hint) >= 6 and full.startswith(hint):
        return True
    if len(full) >= 6 and hint.startswith(full[: min(len(hint), len(full))]):
        return True
    return False


async def report_hash_failure(
    db: AsyncSession,
    user: User,
    hash_hint: str,
    error_type: str,
    message: str,
) -> tuple[bool, str]:
    """Increment fail_count for matching server hash (client-side tunnel/VK errors)."""
    raw = (hash_hint or "").strip()
    normalized = extract_call_hash(raw) or raw
    if len(normalized) < 6:
        return False, "invalid hash hint"

    result = await db.execute(select(VkHash).where(VkHash.user_id == user.id))
    matched: VkHash | None = None
    for row in result.scalars().all():
        hv = (row.hash_value or "").strip()
        if _hash_matches(normalized, hv):
            matched = row
            break

    if matched is None:
        boot = (user.bootstrap_hash or "").strip()
        if boot and _hash_matches(normalized, boot):
            logger.warning(
                "hash failure (bootstrap) user=%s type=%s: %s",
                user.id,
                error_type,
                (message or "")[:200],
            )
            return True, "bootstrap logged"
        return False, "hash not found"

    matched.fail_count = int(matched.fail_count or 0) + 1
    matched.last_failed = datetime.utcnow()
    matched.last_checked = datetime.utcnow()
    if matched.fail_count >= FAIL_COUNT_DEACTIVATE:
        matched.is_active = False
        logger.warning(
            "hash slot %s deactivated (fail_count=%s) user=%s type=%s",
            matched.slot_index,
            matched.fail_count,
            user.id,
            error_type,
        )
    await db.commit()
    return True, f"fail_count={matched.fail_count}"
