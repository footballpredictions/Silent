"""Subscription, trial and admin access helpers."""
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, Subscription
from app.config import settings

TRIAL_PLAN = "trial"


def is_user_admin(user: User) -> bool:
    return bool(user.is_admin) or user.email.lower() == settings.ADMIN_LOGIN.lower()


async def ensure_admin_flag(user: User, db: AsyncSession) -> None:
    """Sync is_admin from ADMIN_LOGIN email once."""
    if user.email.lower() == settings.ADMIN_LOGIN.lower() and not user.is_admin:
        user.is_admin = True
        await db.commit()
        await db.refresh(user)


async def get_active_subscription(db: AsyncSession, user: User) -> Subscription | None:
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    for sub in result.scalars().all():
        if sub.is_active:
            return sub
    return None


async def ensure_trial_subscription(db: AsyncSession, user: User) -> Subscription | None:
    """One-time 3-day trial for users who never had any subscription."""
    if is_user_admin(user):
        return None

    active = await get_active_subscription(db, user)
    if active:
        return active

    result = await db.execute(
        select(Subscription.id).where(Subscription.user_id == user.id).limit(1)
    )
    if result.scalar_one_or_none():
        return None

    now = datetime.utcnow()
    trial = Subscription(
        user_id=user.id,
        plan_type=TRIAL_PLAN,
        status="active",
        amount_paid=0,
        started_at=now,
        expires_at=now + timedelta(days=settings.TRIAL_DAYS),
    )
    db.add(trial)
    await db.commit()
    await db.refresh(trial)
    return trial


async def user_has_active_subscription(user: User, db: AsyncSession) -> bool:
    if is_user_admin(user):
        return True
    await ensure_trial_subscription(db, user)
    sub = await get_active_subscription(db, user)
    return sub is not None


async def require_active_subscription(user: User, db: AsyncSession) -> None:
    """Raise 402 if VPN access is not allowed (trial ended, no paid plan)."""
    if is_user_admin(user):
        return

    await ensure_trial_subscription(db, user)
    sub = await get_active_subscription(db, user)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Пробный период закончился. Оформите подписку для доступа к интернету.",
        )
