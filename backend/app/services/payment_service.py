"""YuMoney payment service — redirects to payment page, verifies via notification."""
import random
import uuid
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models import Payment, User, Subscription, PromoCode
from app.services.email_service import send_subscription_activated_email

logger = logging.getLogger(__name__)

PLAN_PRICES = {
    "monthly": (settings.PRICE_MONTHLY, 30),
    "quarterly": (settings.PRICE_QUARTERLY, 90),
    "yearly": (settings.PRICE_YEARLY, 365),
}


def _pick_wallet() -> str:
    """Randomly select one of two YuMoney wallets."""
    return random.choice([settings.YUMONEY_WALLET_1, settings.YUMONEY_WALLET_2])


def build_payment_url(plan_type: str, label: str, amount: float) -> dict:
    """Build YuMoney QuickPay redirect URL."""
    wallet = _pick_wallet()
    # YuMoney QuickPay URL format
    base_url = "https://yoomoney.ru/quickpay/confirm.xml"
    params = {
        "receiver": wallet,
        "quickpay-form": "send",
        "targets": f"Silent VPN — {plan_type}",
        "paymentType": "AC",
        "sum": str(amount),
        "label": label,
        "successURL": f"{settings.APP_NAME}://payment/success",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return {
        "url": f"{base_url}?{query}",
        "wallet": wallet,
        "label": label,
        "amount": amount,
    }


async def create_payment_intent(
    db: AsyncSession,
    user: User,
    plan_type: str,
    promo_code: Optional[str] = None,
) -> dict:
    if plan_type not in PLAN_PRICES:
        raise ValueError(f"Unknown plan: {plan_type}")

    amount, days = PLAN_PRICES[plan_type]

    # Apply promo code
    if promo_code:
        result = await db.execute(
            select(PromoCode).where(
                PromoCode.code == promo_code.upper(),
                PromoCode.is_active == True,
            )
        )
        promo = result.scalar_one_or_none()
        if promo and promo.use_count < promo.max_uses:
            if promo.expires_at is None or promo.expires_at > datetime.utcnow():
                amount = amount * (1 - promo.discount_percent / 100)
                days += promo.extra_days

    label = f"silent_{user.id}_{uuid.uuid4().hex[:8]}"
    wallet = _pick_wallet()

    payment = Payment(
        user_id=user.id,
        plan_type=plan_type,
        amount=round(amount, 2),
        wallet=wallet,
        yumoney_label=label,
        status="pending",
    )
    db.add(payment)
    await db.commit()

    return build_payment_url(plan_type, label, round(amount, 2))


def _verify_yumoney_signature(data: dict, secret: str) -> bool:
    """Verify YuMoney notification signature."""
    notification_type = data.get("notification_type", "")
    operation_id = data.get("operation_id", "")
    amount = data.get("amount", "")
    currency = data.get("currency", "643")
    datetime_str = data.get("datetime", "")
    sender = data.get("sender", "")
    codepro = data.get("codepro", "false")
    label = data.get("label", "")

    check_str = "&".join([
        notification_type, operation_id, amount, currency,
        datetime_str, sender, codepro, secret, label
    ])
    sha1 = hashlib.sha1(check_str.encode("utf-8")).hexdigest()
    return sha1 == data.get("sha1_hash", "")


async def process_payment_notification(db: AsyncSession, data: dict) -> bool:
    """Handle YuMoney HTTP notification and activate subscription."""
    if not _verify_yumoney_signature(data, settings.YUMONEY_SECRET):
        logger.warning("Invalid YuMoney signature")
        return False

    label = data.get("label", "")
    if not label.startswith("silent_"):
        return False

    result = await db.execute(
        select(Payment).where(Payment.yumoney_label == label, Payment.status == "pending")
    )
    payment = result.scalar_one_or_none()
    if not payment:
        return False

    payment.status = "completed"
    payment.completed_at = datetime.utcnow()
    payment.raw_response = str(data)
    await db.flush()

    # Activate subscription
    _, days = PLAN_PRICES.get(payment.plan_type, (0, 30))
    now = datetime.utcnow()
    subscription = Subscription(
        user_id=payment.user_id,
        plan_type=payment.plan_type,
        status="active",
        amount_paid=float(payment.amount),
        started_at=now,
        expires_at=now + timedelta(days=days),
    )
    db.add(subscription)
    await db.commit()

    # Send email
    result = await db.execute(select(User).where(User.id == payment.user_id))
    user = result.scalar_one_or_none()
    if user:
        send_subscription_activated_email(user.email, payment.plan_type, subscription.expires_at)

    return True
