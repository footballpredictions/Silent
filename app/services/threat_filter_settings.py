"""Threat DNS filter toggle (AppSetting) — HaGeZi TIF via host dnsmasq."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

THREAT_FILTER_ENABLED_KEY = "threat_filter_enabled"
THREAT_FILTER_DOMAINS_COUNT_KEY = "threat_filter_domains_count"
THREAT_FILTER_LIST_UPDATED_AT_KEY = "threat_filter_list_updated_at"

DEFAULT_WG_DNS = "77.88.8.8,77.88.8.1"
FILTER_WG_DNS = "10.66.66.1"


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


async def is_threat_filter_enabled(db: AsyncSession) -> bool:
    row = await _get_setting(db, THREAT_FILTER_ENABLED_KEY)
    return row is not None and _truthy(row.value)


async def set_threat_filter_enabled(db: AsyncSession, enabled: bool) -> bool:
    await _set_setting(db, THREAT_FILTER_ENABLED_KEY, "true" if enabled else "false")
    await db.commit()
    return enabled


async def resolve_wg_dns(db: AsyncSession) -> str:
    if await is_threat_filter_enabled(db):
        return FILTER_WG_DNS
    return DEFAULT_WG_DNS


async def get_threat_filter_status(db: AsyncSession) -> dict:
    enabled = await is_threat_filter_enabled(db)
    count_row = await _get_setting(db, THREAT_FILTER_DOMAINS_COUNT_KEY)
    updated_row = await _get_setting(db, THREAT_FILTER_LIST_UPDATED_AT_KEY)
    domains_count = 0
    if count_row and count_row.value.strip().isdigit():
        domains_count = int(count_row.value.strip())
    list_updated_at = (updated_row.value.strip() if updated_row and updated_row.value else None) or None
    return {
        "enabled": enabled,
        "wg_dns": FILTER_WG_DNS if enabled else DEFAULT_WG_DNS,
        "domains_count": domains_count,
        "list_updated_at": list_updated_at,
        "list_source": "HaGeZi TIF (malware / phishing / scam)",
        "note": (
            "После включения клиентам нужен reconnect VPN, чтобы подтянуть новый DNS. "
            "Списки обновляет systemd на хосте Улья каждые 6 часов."
        ),
    }


async def update_threat_filter_meta(
    db: AsyncSession,
    *,
    domains_count: int,
    list_updated_at: str,
) -> dict:
    await _set_setting(db, THREAT_FILTER_DOMAINS_COUNT_KEY, str(max(0, int(domains_count))))
    await _set_setting(db, THREAT_FILTER_LIST_UPDATED_AT_KEY, list_updated_at.strip())
    await db.commit()
    return await get_threat_filter_status(db)
