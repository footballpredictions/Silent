"""Load and normalize client UI theme from app_settings."""
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting
from app.schemas.vpn import ThemeResponse

_LEGACY_APP_NAMES = frozenset({"", "silent"})


def normalize_theme_data(data: dict) -> dict:
    name = (data.get("app_name") or "").strip()
    if name.lower() in _LEGACY_APP_NAMES:
        out = dict(data)
        out["app_name"] = "Silent VPN"
        return out
    return data


def theme_needs_migration(data: dict) -> bool:
    return (data.get("app_name") or "").strip().lower() in _LEGACY_APP_NAMES


async def load_theme(db: AsyncSession, *, persist_migration: bool = False) -> ThemeResponse:
    result = await db.execute(select(AppSetting).where(AppSetting.key == "theme"))
    setting = result.scalar_one_or_none()
    theme: ThemeResponse
    if not setting:
        theme = ThemeResponse()
    else:
        try:
            raw = json.loads(setting.value)
            normalized = normalize_theme_data(raw)
            if persist_migration and theme_needs_migration(raw):
                setting.value = json.dumps(normalized)
                await db.commit()
            theme = ThemeResponse(**normalized)
        except Exception:
            theme = ThemeResponse()

    if not (theme.hive_standby_api_urls or "").strip():
        try:
            from app.services.hive_standby import standby_api_urls

            urls = await standby_api_urls(db)
            if urls:
                theme.hive_standby_api_urls = ",".join(urls)
        except Exception:
            pass
    return theme
