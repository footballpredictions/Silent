"""Global test mode toggle (AppSetting) — applies to all users while enabled."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting

REGISTRATION_TEST_MODE_KEY = "registration_test_mode"


async def is_registration_test_mode_enabled(db: AsyncSession) -> bool:
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == REGISTRATION_TEST_MODE_KEY)
    )
    row = result.scalar_one_or_none()
    return row is not None and row.value.strip().lower() in ("true", "1", "yes", "on")


async def set_registration_test_mode(db: AsyncSession, enabled: bool) -> tuple[bool, int]:
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == REGISTRATION_TEST_MODE_KEY)
    )
    row = result.scalar_one_or_none()
    value = "true" if enabled else "false"
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=REGISTRATION_TEST_MODE_KEY, value=value))
    await db.commit()

    from app.services.subscription_service import sync_all_users_for_test_mode
    affected = await sync_all_users_for_test_mode(db, enabled)
    return enabled, affected
