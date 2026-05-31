"""Per-user VK call hashes: bootstrap (user) + 3 server slots."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, VkHash, Device
from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

logger = logging.getLogger(__name__)

MAX_SERVER_SLOTS = 3


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


async def get_vpn_hashes_for_user(db: AsyncSession, user: User) -> list[str]:
    """User bootstrap + up to 3 active server hashes (deduped)."""
    out: list[str] = []
    boot = (user.bootstrap_hash or "").strip()
    if boot:
        out.append(boot)
    result = await db.execute(
        select(VkHash.hash_value)
        .where(VkHash.user_id == user.id, VkHash.is_active == True)
        .order_by(VkHash.slot_index)
    )
    for (h,) in result.fetchall():
        h = (h or "").strip()
        if h and h not in out:
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
    result = await db.execute(
        select(VkHash.id).where(
            VkHash.user_id == user_id,
            VkHash.is_active == True,
        )
    )
    return len(result.fetchall())


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
    """Create missing server slots (0–2) via AI agent when enabled."""
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
    """Client asks for 3 new server hashes when only bootstrap remains."""
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
    """Users with bootstrap or server hashes — for AI monitor."""
    result = await db.execute(
        select(User.id).where(
            User.is_active == True,
            User.email != BOOTSTRAP_USER_EMAIL,
            User.bootstrap_hash.isnot(None),
        )
    )
    ids = [row[0] for row in result.fetchall()]
    result2 = await db.execute(
        select(VkHash.user_id).where(VkHash.user_id.isnot(None), VkHash.is_active == True).distinct()
    )
    for (uid,) in result2.fetchall():
        if uid and uid not in ids:
            ids.append(uid)
    return ids
