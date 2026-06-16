"""Subscription, trial and admin access helpers."""
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import User, Subscription
from app.config import settings

logger = logging.getLogger(__name__)

TRIAL_PLAN = "trial"
TEST_PLAN = "test"


def is_user_admin(user: User) -> bool:
    return bool(user.is_admin) or user.email.lower() == settings.ADMIN_LOGIN.lower()


def is_test_user(user: User) -> bool:
    return bool(getattr(user, "is_test_user", False))


async def user_in_test_mode(user: User, db: AsyncSession) -> bool:
    """Test access: per-user flag or global test mode (all non-admin users)."""
    if is_user_admin(user):
        return False
    if is_test_user(user):
        return True
    from app.services.test_mode_settings import is_registration_test_mode_enabled
    return await is_registration_test_mode_enabled(db)


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


async def enroll_user_in_test_mode(db: AsyncSession, user: User) -> Subscription:
    """Mark user as test and grant unlimited-style subscription."""
    if is_user_admin(user):
        raise HTTPException(status_code=400, detail="Администратору тестовый режим не нужен")

    user.is_test_user = True
    now = datetime.utcnow()

    active_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
    )
    for existing in active_result.scalars().all():
        existing.status = "cancelled"

    subscription = Subscription(
        user_id=user.id,
        plan_type=TEST_PLAN,
        status="active",
        amount_paid=0,
        started_at=now,
        expires_at=now + timedelta(days=36500),
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def sync_all_users_for_test_mode(db: AsyncSession, enabled: bool) -> int:
    """Enable/disable test mode for every non-admin user."""
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

    result = await db.execute(select(User))
    affected = 0
    now = datetime.utcnow()

    for user in result.scalars().all():
        if is_user_admin(user) or user.email == BOOTSTRAP_USER_EMAIL:
            continue

        changed = False
        if enabled:
            if not user.is_test_user:
                user.is_test_user = True
                changed = True
            active = await get_active_subscription(db, user)
            if not active:
                db.add(Subscription(
                    user_id=user.id,
                    plan_type=TEST_PLAN,
                    status="active",
                    amount_paid=0,
                    started_at=now,
                    expires_at=now + timedelta(days=36500),
                ))
                changed = True
        else:
            if user.is_test_user:
                user.is_test_user = False
                changed = True
            active_result = await db.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.status == "active",
                    Subscription.plan_type == TEST_PLAN,
                )
            )
            for sub in active_result.scalars().all():
                if sub.is_active:
                    sub.status = "cancelled"
                    changed = True

        if changed:
            affected += 1

    await db.commit()
    return affected


async def apply_post_verification_benefits(db: AsyncSession, user: User) -> Subscription | None:
    """Trial or test mode subscription after email verification."""
    if is_user_admin(user):
        return None

    from app.services.test_mode_settings import is_registration_test_mode_enabled

    sub: Subscription | None
    if await is_registration_test_mode_enabled(db):
        sub = await enroll_user_in_test_mode(db, user)
    else:
        sub = await ensure_trial_subscription(db, user)

    try:
        from app.services.vk_agent_auth import is_agent_enabled
        from app.services.user_hash_service import ensure_user_server_hashes

        if await is_agent_enabled(db):
            created = await ensure_user_server_hashes(db, user.id)
            if created:
                logger.info("post_verify: created %s VK hash slot(s) for user %s", created, user.id)
    except Exception as e:
        logger.warning("post_verify ensure_user_server_hashes failed: %s", e)

    return sub


async def user_has_active_subscription(user: User, db: AsyncSession) -> bool:
    if is_user_admin(user) or await user_in_test_mode(user, db):
        return True
    await ensure_trial_subscription(db, user)
    sub = await get_active_subscription(db, user)
    return sub is not None


async def require_active_subscription(user: User, db: AsyncSession) -> None:
    """Raise 402 if VPN access is not allowed (trial ended, no paid plan)."""
    if is_user_admin(user) or await user_in_test_mode(user, db):
        return

    await ensure_trial_subscription(db, user)
    sub = await get_active_subscription(db, user)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Пробный период закончился. Оформите подписку для доступа к интернету.",
        )


GRANTABLE_PLANS = {
    "three_days": 3,
    "monthly": 30,
    "quarterly": 90,
    "yearly": 365,
    "unlimited": 36500,  # ~100 лет
}


async def grant_manual_subscription(
    db: AsyncSession,
    user: User,
    plan_type: str,
) -> Subscription:
    """Admin grant: cancel active subs, extend from current expiry or now."""
    if plan_type not in GRANTABLE_PLANS:
        raise HTTPException(
            status_code=400,
            detail="plan_type: three_days, monthly, quarterly, yearly или unlimited",
        )
    if is_user_admin(user):
        raise HTTPException(status_code=400, detail="Администратору подписка не нужна")

    days = GRANTABLE_PLANS[plan_type]
    now = datetime.utcnow()

    active_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    # For unlimited always start from now (no stacking needed for ~100 years)
    base = now if plan_type == "unlimited" else now
    for existing in active_result.scalars().all():
        if plan_type != "unlimited" and existing.is_active and existing.expires_at > base:
            base = existing.expires_at
        existing.status = "cancelled"

    subscription = Subscription(
        user_id=user.id,
        plan_type=plan_type,
        status="active",
        amount_paid=0,
        started_at=now,
        expires_at=base + timedelta(days=days),
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def revoke_subscription(db: AsyncSession, user: User) -> int:
    """Cancel all active subscriptions for the user. Returns count cancelled."""
    active_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
    )
    cancelled = 0
    for sub in active_result.scalars().all():
        if sub.is_active:
            sub.status = "cancelled"
            cancelled += 1
    await db.commit()
    return cancelled
