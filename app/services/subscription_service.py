"""Subscription, trial and admin access helpers."""
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, or_

from app.models import User, Subscription, Device
from app.config import settings

logger = logging.getLogger(__name__)

TRIAL_PLAN = "trial"
TEST_PLAN = "test"


def is_user_admin(user: User) -> bool:
    return bool(user.is_admin) or user.email.lower() == settings.ADMIN_LOGIN.lower()


def max_devices_for_user(user: User) -> int:
    """0 = безлимит (админ)."""
    if is_user_admin(user):
        return 0
    return settings.MAX_DEVICES_PER_USER


def device_limit_applies(user: User) -> bool:
    return not is_user_admin(user)


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


def _fingerprint_variants(fingerprint: str) -> set[str]:
    fp = (fingerprint or "").strip()
    if not fp:
        return set()
    raw = fp[5:] if fp.startswith("boot:") else fp
    if not raw:
        return set()
    return {raw, f"boot:{raw}"}


async def device_fingerprint_used_trial_elsewhere(
    db: AsyncSession,
    fingerprint: str,
    *,
    exclude_user_id,
) -> bool:
    """True, если fingerprint уже получал trial у другого аккаунта.

    Режет обход trial через анонимайзер Mail.ru (до 10 алиасов) на одном устройстве.
    """
    variants = _fingerprint_variants(fingerprint)
    if not variants:
        return False

    from app.models import Device

    result = await db.execute(
        select(Device.user_id)
        .join(Subscription, Subscription.user_id == Device.user_id)
        .where(
            Device.device_fingerprint.in_(variants),
            Device.user_id != exclude_user_id,
            Subscription.plan_type == TRIAL_PLAN,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def require_device_trial_not_reused(
    db: AsyncSession,
    user: User,
    fingerprint: str,
) -> None:
    """Блок VPN/trial на устройстве, где trial уже был у другого аккаунта."""
    if is_user_admin(user) or await user_in_test_mode(user, db):
        return

    in_test = await user_in_test_mode(user, db)
    active = await get_display_subscription(db, user, in_test_mode=in_test)
    if active and active.plan_type not in (TRIAL_PLAN, TEST_PLAN):
        return

    if await device_fingerprint_used_trial_elsewhere(
        db, fingerprint, exclude_user_id=user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Пробный период на этом устройстве уже был использован. "
                "Оформите подписку или войдите в прежний аккаунт."
            ),
        )


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
    if restored is None:
        devices = await db.execute(
            select(Device).where(Device.user_id == user.id, Device.is_connected == True)  # noqa: E712
        )
        for device in devices.scalars().all():
            device.is_connected = False
    await db.commit()
    if restored is None:
        try:
            from app.services.vpn_kick import kick_user_vpn_sessions

            await kick_user_vpn_sessions(db, user)
        except Exception as e:
            logger.warning("exit test mode: live VPN kick failed: %s", e, exc_info=True)
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
    try:
        from app.services.vpn_kick import restore_user_vpn_dataplane

        await restore_user_vpn_dataplane(db, user)
    except Exception as e:
        logger.warning("enroll test: restore dataplane failed: %s", e)
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
    result = await db.execute(
        text(
            """
            UPDATE users
            SET is_test_user = false
            WHERE is_test_user = true
              AND COALESCE(test_mode_personal, false) = false
              AND lower(email) <> :admin_email
            """
        ),
        {"admin_email": settings.ADMIN_LOGIN.lower()},
    )
    cleared = result.rowcount or 0
    if cleared:
        await db.commit()
    return cleared


async def cleanup_global_test_subscriptions(db: AsyncSession) -> int:
    """When global test mode turns off: drop overlay test plans and restore paid/trial.

    Must stay set-based: a Python loop over all users holds a pool connection long
    enough to starve admin login and client VPN (QueuePool TimeoutError).
    """
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

    cancelled = await db.execute(
        text(
            """
            UPDATE subscriptions s
            SET status = 'cancelled'
            FROM users u
            WHERE s.user_id = u.id
              AND s.status = 'active'
              AND s.plan_type = :test_plan
              AND COALESCE(u.test_mode_personal, false) = false
              AND lower(u.email) <> :admin_email
              AND u.email <> :bootstrap
            """
        ),
        {
            "test_plan": TEST_PLAN,
            "admin_email": settings.ADMIN_LOGIN.lower(),
            "bootstrap": BOOTSTRAP_USER_EMAIL,
        },
    )
    await db.execute(
        text(
            """
            UPDATE subscriptions s
            SET status = 'active'
            WHERE s.id IN (
              SELECT DISTINCT ON (c.user_id) c.id
              FROM subscriptions c
              WHERE c.status = 'cancelled'
                AND c.plan_type <> :test_plan
                AND c.expires_at > (now() AT TIME ZONE 'utc')
                AND NOT EXISTS (
                  SELECT 1 FROM subscriptions a
                  WHERE a.user_id = c.user_id
                    AND a.status = 'active'
                    AND a.plan_type <> :test_plan
                    AND a.expires_at > (now() AT TIME ZONE 'utc')
                )
              ORDER BY c.user_id, c.expires_at DESC
            )
            """
        ),
        {"test_plan": TEST_PLAN},
    )
    await db.commit()
    return cancelled.rowcount or 0


async def reconcile_stale_test_subscriptions(db: AsyncSession) -> int:
    """Cancel leftover test plans when global test is off; restore paid/trial."""
    from app.services.test_mode_settings import is_registration_test_mode_enabled

    if await is_registration_test_mode_enabled(db):
        return 0
    return await cleanup_global_test_subscriptions(db)


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


async def users_with_vpn_access_ids(db: AsyncSession) -> set:
    """Кто сейчас имеет VPN: один SQL, без ensure_trial и без N+1."""
    from app.services.test_mode_settings import is_registration_test_mode_enabled
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

    now = datetime.utcnow()
    admin_email = (settings.ADMIN_LOGIN or "").lower()
    not_bootstrap = User.email != BOOTSTRAP_USER_EMAIL
    live_sub = (
        select(Subscription.user_id)
        .where(Subscription.status == "active", Subscription.expires_at > now)
        .distinct()
    )
    global_test = await is_registration_test_mode_enabled(db)
    if global_test:
        access = or_(
            User.is_admin.is_(True),
            func.lower(User.email) == admin_email,
            User.test_mode_excluded.is_(False),
            User.id.in_(live_sub),
        )
    else:
        access = or_(
            User.is_admin.is_(True),
            func.lower(User.email) == admin_email,
            User.test_mode_personal.is_(True),
            User.id.in_(live_sub),
        )
    rows = await db.execute(select(User.id).where(not_bootstrap, access))
    return set(rows.scalars().all())


async def has_live_test_plan(db: AsyncSession, user: User) -> bool:
    """Неотменённый test-план ещё действует — не режем канал (сейчас у всех бесплатный тест)."""
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
            Subscription.plan_type == TEST_PLAN,
        )
    )
    return any(sub.is_active for sub in result.scalars().all())


async def user_has_active_subscription(user: User, db: AsyncSession) -> bool:
    if is_user_admin(user) or await user_in_test_mode(user, db):
        return True
    if await has_live_test_plan(db, user):
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
    "two_months": 60,
    "quarterly": 90,
    "half_year": 180,
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
            detail="plan_type: three_days, monthly, two_months, quarterly, half_year, yearly или unlimited",
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
    try:
        from app.services.vpn_kick import restore_user_vpn_dataplane

        await restore_user_vpn_dataplane(db, user)
    except Exception as e:
        logger.warning("grant: restore dataplane failed: %s", e)
    return subscription


async def revoke_subscription(db: AsyncSession, user: User) -> int:
    """Cancel all active subscriptions and drop live VPN sessions."""
    active_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id, Subscription.status == "active")
    )
    cancelled = 0
    for sub in active_result.scalars().all():
        if sub.is_active:
            sub.status = "cancelled"
            cancelled += 1
    user.updated_at = datetime.utcnow()
    devices = await db.execute(
        select(Device).where(Device.user_id == user.id, Device.is_connected == True)  # noqa: E712
    )
    for device in devices.scalars().all():
        device.is_connected = False
    await db.commit()
    try:
        from app.services.vpn_kick import kick_user_vpn_sessions

        await kick_user_vpn_sessions(db, user)
    except Exception as e:
        logger.warning("revoke: live VPN kick failed: %s", e, exc_info=True)
    return cancelled
