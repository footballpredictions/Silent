"""Global registration lock (AppSetting) — blocks new sign-ups during incidents."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

REGISTRATION_DISABLED_KEY = "registration_disabled"

REGISTRATION_DISABLED_MESSAGE = (
    "Ведутся технические работы. Регистрация временно недоступна."
)


async def is_registration_disabled(db: AsyncSession) -> bool:
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == REGISTRATION_DISABLED_KEY)
    )
    row = result.scalar_one_or_none()
    return row is not None and row.value.strip().lower() in ("true", "1", "yes", "on")


async def set_registration_disabled(db: AsyncSession, disabled: bool) -> bool:
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == REGISTRATION_DISABLED_KEY)
    )
    row = result.scalar_one_or_none()
    value = "true" if disabled else "false"
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=REGISTRATION_DISABLED_KEY, value=value))
    await db.commit()
    return disabled
