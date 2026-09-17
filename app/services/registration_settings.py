"""Global registration lock + skip email confirmation (AppSetting)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting
from app.services.email_confirmation_policy import setting_is_on

REGISTRATION_DISABLED_KEY = "registration_disabled"
SKIP_EMAIL_CONFIRMATION_KEY = "skip_email_confirmation"

REGISTRATION_DISABLED_MESSAGE = (
    "Ведутся технические работы. Регистрация временно недоступна."
)


async def _setting_on(db: AsyncSession, key: str) -> bool:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    return setting_is_on(row.value if row else None)


async def _set_bool(db: AsyncSession, key: str, enabled: bool) -> bool:
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    row = result.scalar_one_or_none()
    value = "true" if enabled else "false"
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.commit()
    return enabled


async def is_registration_disabled(db: AsyncSession) -> bool:
    return await _setting_on(db, REGISTRATION_DISABLED_KEY)


async def set_registration_disabled(db: AsyncSession, disabled: bool) -> bool:
    return await _set_bool(db, REGISTRATION_DISABLED_KEY, disabled)


async def is_skip_email_confirmation(db: AsyncSession) -> bool:
    """Default OFF — old clients still require email confirm."""
    return await _setting_on(db, SKIP_EMAIL_CONFIRMATION_KEY)


async def set_skip_email_confirmation(db: AsyncSession, skip: bool) -> bool:
    return await _set_bool(db, SKIP_EMAIL_CONFIRMATION_KEY, skip)
