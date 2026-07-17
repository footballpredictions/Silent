"""All-time peak of concurrent VPN online devices (for admin dashboard)."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting, Device

PEAK_ONLINE_KEY = "peak_online_devices"
PEAK_ONLINE_AT_KEY = "peak_online_at"


async def count_online_devices(db: AsyncSession) -> int:
    return int(
        (
            await db.execute(
                select(func.count(Device.id)).where(Device.is_connected == True)  # noqa: E712
            )
        ).scalar_one()
        or 0
    )


async def get_peak_online(db: AsyncSession) -> tuple[int, str | None]:
    """Return (peak_count, iso_utc_when_set_or_None)."""
    result = await db.execute(
        select(AppSetting).where(AppSetting.key.in_([PEAK_ONLINE_KEY, PEAK_ONLINE_AT_KEY]))
    )
    rows = {r.key: r.value for r in result.scalars().all()}
    try:
        peak = max(0, int(rows.get(PEAK_ONLINE_KEY) or "0"))
    except (TypeError, ValueError):
        peak = 0
    at = (rows.get(PEAK_ONLINE_AT_KEY) or "").strip() or None
    return peak, at


async def _upsert_setting(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


async def record_online_peak(
    db: AsyncSession,
    current: int | None = None,
    *,
    commit: bool = True,
) -> tuple[int, str | None]:
    """If current online > stored peak, update peak. Returns (peak, peak_at)."""
    if current is None:
        current = await count_online_devices(db)
    current = max(0, int(current))

    peak, at = await get_peak_online(db)
    if current > peak:
        peak = current
        at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        await _upsert_setting(db, PEAK_ONLINE_KEY, str(peak))
        await _upsert_setting(db, PEAK_ONLINE_AT_KEY, at)
        if commit:
            await db.commit()
    return peak, at
