"""Subscription and admin access helpers."""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, Subscription
from app.config import settings


def is_user_admin(user: User) -> bool:
    return bool(user.is_admin) or user.email.lower() == settings.ADMIN_LOGIN.lower()


async def ensure_admin_flag(user: User, db: AsyncSession) -> None:
    """Sync is_admin from ADMIN_LOGIN email once."""
    if user.email.lower() == settings.ADMIN_LOGIN.lower() and not user.is_admin:
        user.is_admin = True
        await db.commit()
        await db.refresh(user)


async def user_has_active_subscription(user: User, db: AsyncSession) -> bool:
    if is_user_admin(user):
        return True
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
        ).order_by(Subscription.expires_at.desc())
    )
    sub = result.scalars().first()
    return sub is not None and sub.is_active
