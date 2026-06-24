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
    """Explicit per-user test toggle (not legacy global mass-sync)."""
    return bool(getattr(user, "test_mode_personal", False))


def is_test_mode_excluded(user: User) -> bool:
    return bool(getattr(user, "test_mode_excluded", False))


async def user_in_test_mode(user: User, db: AsyncSession) -> bool:
    """Personal test, or global test mode unless user is excluded."""
    if is_user_admin(user):
        return False
    if is_test_user(user):
        return True
    if is_test_mode_excluded(user):
        return False
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


async def get_display_subscription(
    db: AsyncSession, user: User, *, in_test_mode: bool
) -> Subscription | None:
    """Active subscription for UI/API; ignores stale test rows when not in test mode."""
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    for sub in result.scalars().all():
        if not sub.is_active:
            continue
        if sub.plan_type == TEST_PLAN and not in_test_mode:
            continue
        return sub
    return None


async def ensure_trial_subscription(db: AsyncSession, user: User) -> Subscription | None:
    """One-time 3-day trial for users who never had any subscription."""
    if is_user_admin(user):
        return None

    in_test = await user_in_test_mode(user, db)
    active = await get_display_subscription(db, user, in_test_mode=in_test)
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


async def _cancel_active_test_subscriptions(db: AsyncSession, user: User) -> int:
    cancelled = 0
    active_result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
            Subscription.plan_type == TEST_PLAN,
        )
    )
    for sub in active_result.scalars().all():
        sub.status = "cancelled"
        cancelled += 1
    return cancelled


async def _restore_previous_subscription(db: AsyncSession, user: User) -> Subscription | None:
    """Reactivate latest cancelled non-test subscription still within expiry."""
    now = datetime.utcnow()
    result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == "cancelled",
            Subscription.plan_type != TEST_PLAN,
            Subscription.expires_at > now,
        )
        .order_by(Subscription.expires_at.desc())
    )
    sub = result.scalars().first()
    if not sub:
        return None
    sub.status = "active"
    return sub


async def exit_user_test_mode(db: AsyncSession, user: User, *, excluded: bool = False) -> dict:
    """Leave test mode: clear flags, cancel test subs, restore paid/trial if possible."""
    if is_user_admin(user):
        raise HTTPException(status_code=400, detail="Администратору тестовый режим не нужен")

    user.is_test_user = False
    user.test_mode_personal = False
    user.test_mode_excluded = excluded
    cancelled = await _cancel_active_test_subscriptions(db, user)
    restored = await _restore_previous_subscription(db, user)
    await db.commit()
    return {
        "is_test_user": False,
        "test_mode_personal": False,
        "test_mode_excluded": excluded,
        "cancelled_subscriptions": cancelled,
        "restored_subscription": restored.plan_type if restored else None,
    }


async def enroll_user_in_test_mode(db: AsyncSession, user: User) -> Subscription:
    """Mark user as test and grant unlimited-style subscription."""
    if is_user_admin(user):
        raise HTTPException(status_code=400, detail="Администратору тестовый режим не нужен")

    user.is_test_user = True
    user.test_mode_personal = True
    user.test_mode_excluded = False
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


async def unenroll_user_from_test_mode(db: AsyncSession, user: User) -> int:
    """Disable per-user test mode and cancel test-plan subscriptions."""
    data = await exit_user_test_mode(db, user, excluded=False)
    return data["cancelled_subscriptions"]


async def exclude_user_from_global_test_mode(db: AsyncSession, user: User) -> dict:
    """Opt user out of global test mode while keeping personal test off."""
    return await exit_user_test_mode(db, user, excluded=True)


async def set_user_personal_test_mode(db: AsyncSession, user: User, enabled: bool) -> dict:
    """Toggle per-user test mode; respects global test mode exclusions."""
    from app.services.test_mode_settings import is_registration_test_mode_enabled

    if enabled:
        sub = await enroll_user_in_test_mode(db, user)
        return {"is_test_user": True, "test_mode_personal": True, "test_mode_excluded": False, "expires_at": sub.expires_at}

    global_on = await is_registration_test_mode_enabled(db)
    return await exit_user_test_mode(db, user, excluded=global_on)


async def clear_test_mode_exclusions(db: AsyncSession) -> int:
    """Reset per-user global exclusions when global test mode turns off."""
    result = await db.execute(
        select(User).where(User.test_mode_excluded == True)  # noqa: E712
    )
    users = result.scalars().all()
    for user in users:
        user.test_mode_excluded = False
    await db.commit()
    return len(users)


async def clear_legacy_global_test_flags(db: AsyncSession) -> int:
    """When global test turns off: drop legacy is_test_user mass-sync; keep test_mode_personal only."""
    result = await db.execute(select(User))
    cleared = 0
    for user in result.scalars().all():
        if is_user_admin(user):
            continue
        changed = False
        if user.is_test_user and not getattr(user, "test_mode_personal", False):
            user.is_test_user = False
            changed = True
        if changed:
            cleared += 1
    if cleared:
        await db.commit()
    return cleared


async def cleanup_global_test_subscriptions(db: AsyncSession) -> int:
    """When global test mode turns off, cancel test subs for users without individual flag."""
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

    affected = 0
    result = await db.execute(select(User))
    for user in result.scalars().all():
        if is_user_admin(user) or user.email == BOOTSTRAP_USER_EMAIL or is_test_user(user):
            continue
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
                affected += 1
    await db.commit()
    return affected


async def reconcile_stale_test_subscriptions(db: AsyncSession) -> int:
    """Cancel test subs left in DB for users no longer in test mode."""
    from app.services.test_mode_settings import is_registration_test_mode_enabled

    global_test = await is_registration_test_mode_enabled(db)
    fixed = 0
    result = await db.execute(select(User))
    for user in result.scalars().all():
        if is_user_admin(user):
            continue
        in_test = is_test_user(user) or (global_test and not is_test_mode_excluded(user))
        if in_test:
            continue
        cancelled = await _cancel_active_test_subscriptions(db, user)
        if cancelled:
            await _restore_previous_subscription(db, user)
            fixed += cancelled
    if fixed:
        await db.commit()
    return fixed


async def apply_post_verification_benefits(db: AsyncSession, user: User) -> Subscription | None:
    """Trial or test mode subscription after email verification."""
    if is_user_admin(user):
        return None

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
    sub = await get_display_subscription(db, user, in_test_mode=False)
    return sub is not None


async def require_active_subscription(user: User, db: AsyncSession) -> None:
    """Raise 402 if VPN access is not allowed (trial ended, no paid plan)."""
    if is_user_admin(user) or await user_in_test_mode(user, db):
        return

    await ensure_trial_subscription(db, user)
    sub = await get_display_subscription(db, user, in_test_mode=False)
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
