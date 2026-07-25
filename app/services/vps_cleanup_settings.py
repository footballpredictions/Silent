"""VPS auto-cleanup (journal / unused Docker / tmp) — admin toggle + schedule."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

ENABLED_KEY = "vps_cleanup_enabled"
INTERVAL_DAYS_KEY = "vps_cleanup_interval_days"
JOURNAL_MB_KEY = "vps_cleanup_journal_mb"
RUN_NOW_KEY = "vps_cleanup_run_now"
LAST_RUN_AT_KEY = "vps_cleanup_last_run_at"
LAST_SUMMARY_KEY = "vps_cleanup_last_summary"

DEFAULT_INTERVAL_DAYS = 7
DEFAULT_JOURNAL_MB = 200


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in ("true", "1", "yes", "on")


async def _get_setting(db: AsyncSession, key: str) -> AppSetting | None:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    return result.scalar_one_or_none()


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await _get_setting(db, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def _clamp_int(raw: str | None, default: int, lo: int, hi: int) -> int:
    try:
        n = int(str(raw or "").strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


async def get_vps_cleanup_status(db: AsyncSession) -> dict:
    en_row = await _get_setting(db, ENABLED_KEY)
    int_row = await _get_setting(db, INTERVAL_DAYS_KEY)
    j_row = await _get_setting(db, JOURNAL_MB_KEY)
    rn_row = await _get_setting(db, RUN_NOW_KEY)
    last_row = await _get_setting(db, LAST_RUN_AT_KEY)
    sum_row = await _get_setting(db, LAST_SUMMARY_KEY)
    enabled = en_row is not None and _truthy(en_row.value)
    interval_days = _clamp_int(
        int_row.value if int_row else None, DEFAULT_INTERVAL_DAYS, 1, 30
    )
    journal_max_mb = _clamp_int(
        j_row.value if j_row else None, DEFAULT_JOURNAL_MB, 50, 2000
    )
    return {
        "enabled": enabled,
        "interval_days": interval_days,
        "journal_max_mb": journal_max_mb,
        "run_now": rn_row is not None and _truthy(rn_row.value),
        "last_run_at": (last_row.value.strip() if last_row and last_row.value else None) or None,
        "last_summary": (sum_row.value.strip() if sum_row and sum_row.value else None) or None,
        "note": (
            "На Улье: systemd timer опрашивает API. Чистит journal, apt cache, /tmp deploy-junk, "
            "неиспользуемые Docker images и build cache. Volumes/БД/OTA не трогает. "
            "При включении можно сразу запустить очистку (run_now)."
        ),
    }


async def set_vps_cleanup(
    db: AsyncSession,
    *,
    enabled: bool,
    interval_days: int | None = None,
    journal_max_mb: int | None = None,
    run_now: bool | None = None,
) -> dict:
    was_enabled = False
    en_row = await _get_setting(db, ENABLED_KEY)
    if en_row is not None and _truthy(en_row.value):
        was_enabled = True

    await _set_setting(db, ENABLED_KEY, "true" if enabled else "false")
    if interval_days is not None:
        await _set_setting(
            db,
            INTERVAL_DAYS_KEY,
            str(_clamp_int(str(interval_days), DEFAULT_INTERVAL_DAYS, 1, 30)),
        )
    if journal_max_mb is not None:
        await _set_setting(
            db,
            JOURNAL_MB_KEY,
            str(_clamp_int(str(journal_max_mb), DEFAULT_JOURNAL_MB, 50, 2000)),
        )
    if not enabled:
        await _set_setting(db, RUN_NOW_KEY, "false")
    elif run_now is not None:
        await _set_setting(db, RUN_NOW_KEY, "true" if run_now else "false")
    elif not was_enabled:
        # Первое включение тумблера → сразу одна очистка
        await _set_setting(db, RUN_NOW_KEY, "true")
    await db.commit()
    return await get_vps_cleanup_status(db)


async def get_vps_cleanup_host_payload(db: AsyncSession) -> dict:
    """S2S payload for host cleaner script."""
    st = await get_vps_cleanup_status(db)
    return {
        "enabled": st["enabled"],
        "interval_days": st["interval_days"],
        "journal_max_mb": st["journal_max_mb"],
        "run_now": st["run_now"],
        "last_run_at": st["last_run_at"],
    }


async def update_vps_cleanup_meta(
    db: AsyncSession,
    *,
    summary: str,
    clear_run_now: bool = True,
) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await _set_setting(db, LAST_RUN_AT_KEY, now)
    await _set_setting(db, LAST_SUMMARY_KEY, (summary or "")[:2000])
    if clear_run_now:
        await _set_setting(db, RUN_NOW_KEY, "false")
    await db.commit()
    return await get_vps_cleanup_status(db)
