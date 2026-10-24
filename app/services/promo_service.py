"""Eligibility and bounded reservations for first-payment promotions."""
from datetime import datetime
from sqlalchemy import func, select

from app.models import Payment, PromoCode, User


async def has_completed_payment(db, user_id) -> bool:
    result = await db.execute(select(Payment.id).where(
        Payment.user_id == user_id, Payment.status == 'completed',
    ).limit(1))
    return result.scalar_one_or_none() is not None


async def reserve_first_payment_promo(db, user, code, plan_type, amount):
    result = await db.execute(select(PromoCode).where(PromoCode.code == code).with_for_update())
    promo = result.scalar_one_or_none()
    if not promo or not getattr(promo, 'first_payment_only', False):
        return None
    if not promo.is_active or (promo.expires_at is not None and promo.expires_at <= datetime.utcnow()):
        raise ValueError('Промокод больше недействителен')
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    if await has_completed_payment(db, user.id):
        raise ValueError('Промокод доступен только для первой оплаты')
    result = await db.execute(select(Payment).join(PromoCode, Payment.promo_code == PromoCode.code).where(
        Payment.user_id == user.id, PromoCode.first_payment_only.is_(True),
        Payment.status.in_(['pending', 'expired']),
    ).limit(1))
    existing = result.scalar_one_or_none()
    if existing:
        if existing.promo_code != code or existing.plan_type != plan_type or float(existing.amount) != amount:
            raise ValueError('Первая оплата со скидкой уже подготовлена для другого тарифа. Завершите её или обратитесь в поддержку')
        return existing
    result = await db.execute(select(func.count()).select_from(Payment).where(
        Payment.promo_code == code, Payment.status.in_(['pending', 'expired']),
    ))
    if promo.use_count + result.scalar_one() >= promo.max_uses:
        raise ValueError('Все применения промокода уже использованы или зарезервированы для оплаты')
    return None
