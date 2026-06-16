"""Revision counters for client config sync (hashes, theme, profile)."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, Device, Subscription, User, VkHash


def _dt_rev(dt: datetime | None) -> int:
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


async def hashes_revision(db: AsyncSession, user: User) -> int:
    result = await db.execute(
        select(func.max(VkHash.updated_at)).where(VkHash.user_id == user.id)
    )
    max_hash = result.scalar_one_or_none()
    return max(_dt_rev(max_hash), _dt_rev(user.updated_at))


async def theme_revision(db: AsyncSession) -> int:
    result = await db.execute(select(AppSetting).where(AppSetting.key == "theme"))
    setting = result.scalar_one_or_none()
    return _dt_rev(setting.updated_at) if setting else 0


async def profile_revision(db: AsyncSession, user_id: UUID) -> int:
    dev_result = await db.execute(
        select(
            func.max(Device.last_connected),
            func.max(Device.created_at),
        ).where(Device.user_id == user_id, Device.is_active == True)
    )
    dev_row = dev_result.one_or_none()
    dev_rev = 0
    if dev_row:
        dev_rev = max(_dt_rev(dev_row[0]), _dt_rev(dev_row[1]))

    sub_result = await db.execute(
        select(
            func.max(Subscription.expires_at),
            func.max(Subscription.started_at),
            func.max(Subscription.created_at),
        ).where(Subscription.user_id == user_id)
    )
    sub_row = sub_result.one_or_none()
    sub_rev = 0
    if sub_row:
        sub_rev = max(_dt_rev(sub_row[0]), _dt_rev(sub_row[1]), _dt_rev(sub_row[2]))

    return max(dev_rev, sub_rev)


async def build_sync_state(
    db: AsyncSession,
    user: User,
    *,
    hashes_since: int = 0,
    theme_since: int = 0,
    profile_since: int = 0,
) -> dict:
    """Per-section since — иначе max(since) скрывает изменения темы/хешей."""
    h = await hashes_revision(db, user)
    t = await theme_revision(db)
    p = await profile_revision(db, user.id)
    revision = max(h, t, p)

    changed: list[str] = []
    if h > max(0, hashes_since):
        changed.append("hashes")
    if t > max(0, theme_since):
        changed.append("theme")
    if p > max(0, profile_since):
        changed.append("profile")

    return {
        "revision": revision,
        "hashes": h,
        "theme": t,
        "profile": p,
        "changed": changed,
    }
