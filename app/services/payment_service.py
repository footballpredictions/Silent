"""YuMoney payment service — QuickPay redirect + HTTP notification, no API.

Attribution model: every payment intent gets a high-entropy random `label`
(`silent_<32 hex chars>`), stored with the intent and echoed back by YuMoney
in the notification. The label is the only thing used to match a
notification to a specific payment — this is what makes concurrent payments
from different users unambiguous even though they may complete out of order.

Multi-wallet: up to 10 wallets configured purely via env vars
(YUMONEY_WALLET_1..10 / YUMONEY_SECRET_1..10). Adding wallet #11 support
would still only require extending the range below — no other code changes.
"""
import random
import secrets
import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode, quote

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models import Payment, User, Subscription, PromoCode
from app.services.email_service import send_subscription_activated_email

logger = logging.getLogger(__name__)

PLAN_PRICES = {
    "monthly": (settings.PRICE_MONTHLY, 30),
    "two_months": (settings.PRICE_TWO_MONTHS, 60),
    "quarterly": (settings.PRICE_QUARTERLY, 90),  # 3 месяца
    "yearly": (settings.PRICE_YEARLY, 365),  # старые клиенты 1.0.160/161
}

MAX_WALLETS = 10
YUMONEY_QUICKPAY_URL = "https://yoomoney.ru/quickpay/confirm.xml"

# Без O/0/I/1 — удобно диктовать в поддержку
_SUPPORT_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_support_code() -> str:
    """Код вида SV-A7K2-9M3Q для письма и админки."""
    left = "".join(secrets.choice(_SUPPORT_CODE_ALPHABET) for _ in range(4))
    right = "".join(secrets.choice(_SUPPORT_CODE_ALPHABET) for _ in range(4))
    return f"SV-{left}-{right}"


def normalize_support_code(raw: str) -> str:
    s = (raw or "").strip().upper().replace(" ", "")
    if s.startswith("SV") and "-" not in s and len(s) >= 10:
        # SVXXXXYYYY → SV-XXXX-YYYY
        body = s[2:]
        if len(body) == 8:
            s = f"SV-{body[:4]}-{body[4:]}"
    return s


def get_wallets() -> list[dict]:
    """All configured wallets (env-driven, up to MAX_WALLETS). Empty slots skipped."""
    wallets = []
    for i in range(1, MAX_WALLETS + 1):
        wallet = (getattr(settings, f"YUMONEY_WALLET_{i}", "") or "").strip()
        if not wallet:
            continue
        secret = (getattr(settings, f"YUMONEY_SECRET_{i}", "") or "").strip() or settings.YUMONEY_SECRET
        wallets.append({"wallet": wallet, "secret": secret})
    return wallets


def _pick_wallet() -> dict:
    """Randomly select one configured wallet — spreads funds across all of them."""
    wallets = get_wallets()
    if not wallets:
        raise RuntimeError(
            "No YuMoney wallets configured — set YUMONEY_WALLET_1 (and _SECRET_1) at minimum"
        )
    return random.choice(wallets)


def secret_for_wallet(wallet: str) -> str:
    """Notification secret for a specific wallet address; falls back to shared secret."""
    for w in get_wallets():
        if w["wallet"] == wallet:
            return w["secret"]
    return settings.YUMONEY_SECRET


def success_url() -> str:
    """Public backend page YuMoney redirects the browser to after payment."""
    return f"{settings.FRONTEND_URL.rstrip('/')}/api/payments/success-page"


def build_payment_url(plan_type: str, label: str, amount: float, wallet: str) -> str:
    """Build YuMoney QuickPay redirect URL (properly URL-encoded)."""
    params = {
        "receiver": wallet,
        "quickpay-form": "shop",
        "targets": f"Silent VPN - {plan_type}",
        "paymentType": "AC",
        "sum": f"{amount:.2f}",
        "label": label,
        "successURL": success_url(),
    }
    return f"{YUMONEY_QUICKPAY_URL}?{urlencode(params)}"


async def create_payment_intent(
    db: AsyncSession,
    user: User,
    plan_type: str,
    promo_code: Optional[str] = None,
) -> dict:
    if plan_type not in PLAN_PRICES:
        raise ValueError(f"Unknown plan: {plan_type}")

    amount, _days = PLAN_PRICES[plan_type]

    # Prefer explicit promo from client; else pending promo from registration
    code = (promo_code or getattr(user, "pending_promo_code", None) or "").strip().upper() or None
    applied_code = None

    if code:
        result = await db.execute(
            select(PromoCode).where(
                PromoCode.code == code,
                PromoCode.is_active == True,  # noqa: E712
            )
        )
        promo = result.scalar_one_or_none()
        if promo and promo.use_count < promo.max_uses:
            if promo.expires_at is None or promo.expires_at > datetime.utcnow():
                amount = amount * (1 - promo.discount_percent / 100)
                applied_code = promo.code
                # use_count incremented only on successful payment (process_payment_notification),
                # not here — otherwise an abandoned/failed payment would burn the promo for nothing.

    amount = round(amount, 2)
    label = f"silent_{secrets.token_hex(16)}"
    wallet = _pick_wallet()["wallet"]

    payment = Payment(
        user_id=user.id,
        plan_type=plan_type,
        amount=amount,
        wallet=wallet,
        yumoney_label=label,
        status="pending",
        promo_code=applied_code,
    )
    db.add(payment)
    await db.commit()

    logger.info(
        "payment init: user=%s plan=%s amount=%.2f wallet=%s label=%s",
        user.id, plan_type, amount, wallet, label,
    )

    return {
        "url": build_payment_url(plan_type, label, amount, wallet),
        "wallet": wallet,
        "label": label,
        "amount": amount,
    }


def _verify_yumoney_sign(data: dict, secret: str) -> bool:
    """Verify the current `sign` param (HMAC-SHA256 over sorted, URL-encoded params).

    Since 2026-05-18 YuMoney no longer sends `sha1_hash` at all — `sign` is the
    only signature they emit now. Algorithm (docs.yoomoney.ru notification-p2p-incoming):
    take every param except `sign`, sort keys A-Z, URL-encode (RFC 3986) each
    value, join as `key=value` with `&` (empty value -> `key=`), then HMAC-SHA256
    the resulting string with the notification secret, hex-encoded lowercase.
    """
    sign = data.get("sign", "")
    if not secret or not sign:
        return False
    parts = []
    for key in sorted(k for k in data.keys() if k != "sign"):
        value = data.get(key) or ""
        parts.append(f"{key}={quote(str(value), safe='')}")
    check_str = "&".join(parts)
    computed = hmac.new(secret.encode("utf-8"), check_str.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, sign)


def _verify_yumoney_sha1(data: dict, secret: str) -> bool:
    """Legacy `sha1_hash` verification — kept as a fallback, though YuMoney stopped
    sending this parameter entirely as of 2026-05-18."""
    if not secret:
        return False
    sha1_hash = data.get("sha1_hash", "")
    if not sha1_hash:
        return False
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
        datetime_str, sender, codepro, secret, label,
    ])
    sha1 = hashlib.sha1(check_str.encode("utf-8")).hexdigest()
    return hmac.compare_digest(sha1, sha1_hash)


def _verify_yumoney_signature(data: dict, secret: str) -> bool:
    """Verify a YuMoney notification with whichever signature it actually sent."""
    return _verify_yumoney_sign(data, secret) or _verify_yumoney_sha1(data, secret)


def _signature_valid_for_any_wallet(data: dict) -> bool:
    """Used only when the label doesn't match a known payment (e.g. cabinet test notification)."""
    for w in get_wallets():
        if _verify_yumoney_signature(data, w["secret"]):
            return True
    return bool(settings.YUMONEY_SECRET) and _verify_yumoney_signature(data, settings.YUMONEY_SECRET)


async def _activate_subscription(db: AsyncSession, payment: Payment) -> Subscription:
    from app.services.subscription_service import TRIAL_PLAN

    trial_result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == payment.user_id,
            Subscription.plan_type == TRIAL_PLAN,
            Subscription.status == "active",
        )
    )
    for trial in trial_result.scalars().all():
        trial.status = "cancelled"

    _, days = PLAN_PRICES.get(payment.plan_type, (0, 30))
    now = datetime.utcnow()
    active_result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == payment.user_id, Subscription.status == "active")
        .order_by(Subscription.expires_at.desc())
    )
    base = now
    for existing in active_result.scalars().all():
        if existing.is_active and existing.expires_at > base:
            base = existing.expires_at
        existing.status = "cancelled"

    subscription = Subscription(
        user_id=payment.user_id,
        plan_type=payment.plan_type,
        status="active",
        amount_paid=float(payment.amount),
        started_at=now,
        expires_at=base + timedelta(days=days),
    )
    db.add(subscription)
    return subscription


async def process_payment_notification(db: AsyncSession, data: dict) -> dict:
    """
    Handle YuMoney HTTP notification.

    Returns {"ok": bool, "reason": str}:
    - ok=False (invalid signature) → caller should respond 400 (never trust unsigned data).
    - ok=True → caller responds 200 in all cases (including ignored/duplicate/failed), so
      YuMoney does not endlessly retry a notification we already understood.
    """
    label = (data.get("label") or "").strip()
    operation_id = (data.get("operation_id") or "").strip()

    payment = None
    if label.startswith("silent_"):
        result = await db.execute(
            select(Payment).where(Payment.yumoney_label == label).with_for_update()
        )
        payment = result.scalar_one_or_none()

    if not payment:
        if not _signature_valid_for_any_wallet(data):
            logger.warning("payment notify: invalid signature, unknown/foreign label=%r", label)
            return {"ok": False, "reason": "invalid_signature"}
        logger.info("payment notify: signature ok but no matching payment for label=%r — ignoring", label)
        return {"ok": True, "reason": "unknown_label"}

    secret = secret_for_wallet(payment.wallet)
    if not _verify_yumoney_signature(data, secret):
        logger.warning(
            "payment notify: invalid signature for label=%s wallet=%s", label, payment.wallet
        )
        return {"ok": False, "reason": "invalid_signature"}

    if payment.status != "pending":
        # Duplicate notification for an already-settled payment — respond 200, do nothing.
        logger.info("payment notify: payment %s already %s — idempotent", payment.id, payment.status)
        return {"ok": True, "reason": "already_processed"}

    codepro = (data.get("codepro") or "false").strip().lower()
    unaccepted = (data.get("unaccepted") or "false").strip().lower()
    currency = (data.get("currency") or "643").strip()

    if codepro == "true":
        logger.warning("payment notify: codepro=true for payment=%s — protected code, funds withheld", payment.id)
        return {"ok": True, "reason": "codepro"}
    if unaccepted == "true":
        logger.warning("payment notify: unaccepted=true for payment=%s", payment.id)
        return {"ok": True, "reason": "unaccepted"}
    if currency != "643":
        logger.warning("payment notify: unexpected currency=%s for payment=%s", currency, payment.id)
        return {"ok": True, "reason": "bad_currency"}

    if operation_id:
        dup_result = await db.execute(
            select(Payment.id).where(Payment.operation_id == operation_id)
        )
        if dup_result.scalar_one_or_none():
            logger.info("payment notify: duplicate operation_id=%s", operation_id)
            return {"ok": True, "reason": "duplicate_operation"}

    try:
        received = float(data.get("withdraw_amount") or data.get("amount") or 0)
    except (TypeError, ValueError):
        received = 0.0

    expected = float(payment.amount)
    tolerance = settings.YUMONEY_AMOUNT_TOLERANCE
    if expected > 0 and received < expected * tolerance:
        logger.warning(
            "payment notify: amount mismatch label=%s expected=%.2f got=%.2f (min=%.2f) — marking failed",
            label, expected, received, expected * tolerance,
        )
        payment.status = "failed"
        payment.raw_response = str(data)
        await db.commit()
        return {"ok": True, "reason": "amount_mismatch"}

    payment.status = "completed"
    payment.completed_at = datetime.utcnow()
    payment.operation_id = operation_id or None
    payment.paid_amount = round(received, 2)
    payment.raw_response = str(data)
    if not payment.support_code:
        # Уникальный код для письма / ручной выдачи в админке
        for _ in range(8):
            code = generate_support_code()
            exists = await db.execute(
                select(Payment.id).where(Payment.support_code == code)
            )
            if exists.scalar_one_or_none() is None:
                payment.support_code = code
                break
        if not payment.support_code:
            payment.support_code = f"SV-{secrets.token_hex(4).upper()}"
    await db.flush()

    if payment.promo_code:
        promo_result = await db.execute(
            select(PromoCode).where(PromoCode.code == payment.promo_code)
        )
        promo = promo_result.scalar_one_or_none()
        if promo:
            promo.use_count += 1
        user_result = await db.execute(select(User).where(User.id == payment.user_id))
        applied_user = user_result.scalar_one_or_none()
        if applied_user and getattr(applied_user, "pending_promo_code", None) == payment.promo_code:
            applied_user.pending_promo_code = None

    subscription = None
    subscription_ok = False
    try:
        subscription = await _activate_subscription(db, payment)
        payment.subscription_applied = True
        subscription_ok = True
        await db.commit()
    except Exception:
        logger.exception(
            "payment notify: activate failed payment=%s — money kept, support_code=%s",
            payment.id,
            payment.support_code,
        )
        payment.subscription_applied = False
        await db.commit()

    if subscription_ok:
        from app.services.subscription_service import invalidate_vpn_access_cache
        invalidate_vpn_access_cache()
        from app.services.referral_service import apply_referral_reward_after_payment
        try:
            await apply_referral_reward_after_payment(db, payment)
        except Exception:
            logger.exception("payment notify: referral reward failed payment=%s", payment.id)

    result = await db.execute(select(User).where(User.id == payment.user_id))
    user = result.scalar_one_or_none()
    if subscription_ok and user:
        try:
            from app.services.vpn_kick import restore_user_vpn_dataplane

            await restore_user_vpn_dataplane(db, user)
        except Exception:
            logger.exception("payment notify: restore dataplane failed payment=%s", payment.id)
    if user:
        expires = None
        if subscription is not None:
            expires = subscription.expires_at
        else:
            sub_result = await db.execute(
                select(Subscription)
                .where(Subscription.user_id == payment.user_id, Subscription.status == "active")
                .order_by(Subscription.expires_at.desc())
            )
            latest = sub_result.scalars().first()
            if latest:
                expires = latest.expires_at
            else:
                _, days = PLAN_PRICES.get(payment.plan_type, (0, 30))
                expires = datetime.utcnow() + timedelta(days=days)
        try:
            send_subscription_activated_email(
                user.email,
                payment.plan_type,
                expires,
                support_code=payment.support_code,
                subscription_ok=subscription_ok,
            )
        except Exception:
            logger.exception("payment notify: email failed payment=%s", payment.id)

    logger.info(
        "payment notify: payment=%s completed applied=%s code=%s",
        payment.id,
        subscription_ok,
        payment.support_code,
    )
    return {"ok": True, "reason": "completed"}


async def get_payment_status(db: AsyncSession, user: User, label: str) -> dict:
    """Read-only status lookup for client polling. Lazily expires stale pending intents."""
    result = await db.execute(
        select(Payment).where(Payment.yumoney_label == label, Payment.user_id == user.id)
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise ValueError("not_found")

    if payment.status == "pending":
        created = payment.created_at or datetime.utcnow()
        ttl = timedelta(minutes=settings.YUMONEY_PAYMENT_TTL_MINUTES)
        if datetime.utcnow() - created > ttl:
            payment.status = "expired"
            await db.commit()

    return {
        "label": payment.yumoney_label,
        "status": payment.status,
        "plan_type": payment.plan_type,
        "amount": float(payment.amount),
    }
