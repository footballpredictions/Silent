"""Referral codes, registration binding, and post-payment rewards."""
import secrets
import string
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User, Payment, PromoCode, ReferralReward, Subscription

REFERRAL_BONUS_DAYS = settings.REFERRAL_BONUS_DAYS
REFERRAL_MONTHLY_REWARD_LIMIT = settings.REFERRAL_MONTHLY_REWARD_LIMIT
REFERRAL_PLAN = "referral_bonus"
REFERRAL_CODE_ALPHABET = string.ascii_uppercase + string.digits
REFERRAL_CODE_LEN = 8


def normalize_code(raw: str | None) -> str | None:
    if raw is None:
        return None
    code = raw.strip().upper()
    return code or None


def build_referral_link(code: str) -> str:
    return f"silentvpn://ref?code={code}"


async def generate_unique_referral_code(db: AsyncSession) -> str:
    for _ in range(32):
        code = "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(REFERRAL_CODE_LEN))
        existing = await db.execute(select(User.id).where(User.referral_code == code))
        if existing.scalar_one_or_none() is None:
            return code
    raise RuntimeError("Failed to generate unique referral code")


async def ensure_referral_code(db: AsyncSession, user: User) -> str:
    if user.referral_code:
        return user.referral_code
    user.referral_code = await generate_unique_referral_code(db)
    await db.commit()
    await db.refresh(user)
    return user.referral_code


async def find_valid_promo(db: AsyncSession, code: str) -> PromoCode | None:
    result = await db.execute(
        select(PromoCode).where(
            PromoCode.code == code,
            PromoCode.is_active == True,  # noqa: E712
        )
    )
    promo = result.scalar_one_or_none()
    if not promo:
        return None
    if promo.use_count >= promo.max_uses:
        return None
    if promo.expires_at is not None and promo.expires_at <= datetime.utcnow():
        return None
    return promo


async def resolve_referral_or_promo(
    db: AsyncSession,
    code: str | None,
) -> tuple[User | None, PromoCode | None]:
    """Return (inviter, promo). At most one is set. Raises 400 if code invalid."""
    normalized = normalize_code(code)
    if not normalized:
        return None, None

    inviter_result = await db.execute(
        select(User).where(User.referral_code == normalized)
    )
    inviter = inviter_result.scalar_one_or_none()
    if inviter:
        if not inviter.is_active:
            raise HTTPException(status_code=400, detail="Реферальный код недействителен")
        return inviter, None

    promo = await find_valid_promo(db, normalized)
    if promo:
        return None, promo

    raise HTTPException(
        status_code=400,
        detail="Неверный промокод или реферальный код",
    )


async def bind_referral_on_register(
    db: AsyncSession,
    user: User,
    inviter: User | None,
    promo: PromoCode | None,
) -> None:
    if inviter:
        if inviter.id == user.id:
            raise HTTPException(status_code=400, detail="Нельзя использовать свой реферальный код")
        user.referred_by_user_id = inviter.id
        db.add(
            ReferralReward(
                inviter_id=inviter.id,
                invitee_id=user.id,
                status="pending",
            )
        )
    elif promo:
        user.pending_promo_code = promo.code


async def extend_subscription_days(
    db: AsyncSession,
    user_id,
    days: int,
    plan_type: str = REFERRAL_PLAN,
) -> Subscription:
    """Stack +days onto the latest active subscription (or create from now)."""
    now = datetime.utcnow()
    active_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    base = now
    for existing in active_result.scalars().all():
        if existing.is_active and existing.expires_at and existing.expires_at > base:
            base = existing.expires_at

    subscription = Subscription(
        user_id=user_id,
        plan_type=plan_type,
        status="active",
        amount_paid=0,
        started_at=now,
        expires_at=base + timedelta(days=days),
        promo_code=None,
    )
    # Keep previous active rows; stacking via new row with later expires_at
    # is enough for get_active_subscription (orders by expires_at desc).
    db.add(subscription)
    return subscription


async def count_inviter_rewards_last_30_days(db: AsyncSession, inviter_id) -> int:
    since = datetime.utcnow() - timedelta(days=30)
    result = await db.execute(
        select(func.count())
        .select_from(ReferralReward)
        .where(
            ReferralReward.inviter_id == inviter_id,
            ReferralReward.status == "rewarded",
            ReferralReward.rewarded_at.is_not(None),
            ReferralReward.rewarded_at >= since,
        )
    )
    return int(result.scalar_one() or 0)


async def apply_referral_reward_after_payment(
    db: AsyncSession,
    payment: Payment,
) -> bool:
    """
    After invitee's first completed payment: +N days to invitee and (usually) inviter.
    Inviter bonus skipped if monthly reward limit reached (invitee still gets bonus).
    Idempotent via ReferralReward.status.
    """
    reward_result = await db.execute(
        select(ReferralReward).where(
            ReferralReward.invitee_id == payment.user_id,
            ReferralReward.status == "pending",
        )
    )
    reward = reward_result.scalar_one_or_none()
    if not reward:
        return False

    # First completed payment only (current payment already marked completed)
    completed_count = await db.execute(
        select(func.count())
        .select_from(Payment)
        .where(
            Payment.user_id == payment.user_id,
            Payment.status == "completed",
        )
    )
    if int(completed_count.scalar_one() or 0) != 1:
        return False

    await extend_subscription_days(db, payment.user_id, REFERRAL_BONUS_DAYS)

    inviter_recent = await count_inviter_rewards_last_30_days(db, reward.inviter_id)
    if inviter_recent < REFERRAL_MONTHLY_REWARD_LIMIT:
        await extend_subscription_days(db, reward.inviter_id, REFERRAL_BONUS_DAYS)

    reward.status = "rewarded"
    reward.rewarded_at = datetime.utcnow()
    reward.payment_id = payment.id
    await db.commit()
    return True


async def get_referral_stats(db: AsyncSession, user: User) -> dict:
    code = await ensure_referral_code(db, user)
    invited = await db.execute(
        select(func.count())
        .select_from(ReferralReward)
        .where(ReferralReward.inviter_id == user.id)
    )
    rewarded = await db.execute(
        select(func.count())
        .select_from(ReferralReward)
        .where(
            ReferralReward.inviter_id == user.id,
            ReferralReward.status == "rewarded",
        )
    )
    pending = await db.execute(
        select(func.count())
        .select_from(ReferralReward)
        .where(
            ReferralReward.inviter_id == user.id,
            ReferralReward.status == "pending",
        )
    )
    rewarded_last_30d = await count_inviter_rewards_last_30_days(db, user.id)
    return {
        "referral_code": code,
        "referral_link": build_referral_link(code),
        "invited_count": int(invited.scalar_one() or 0),
        "rewarded_count": int(rewarded.scalar_one() or 0),
        "pending_count": int(pending.scalar_one() or 0),
        "bonus_days": REFERRAL_BONUS_DAYS,
        "monthly_reward_limit": REFERRAL_MONTHLY_REWARD_LIMIT,
        "rewarded_last_30_days": rewarded_last_30d,
    }
