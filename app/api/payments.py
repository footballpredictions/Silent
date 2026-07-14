import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import User, PromoCode
from app.core.deps import get_verified_user
from app.services.payment_service import (
    create_payment_intent,
    process_payment_notification,
    get_payment_status,
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


class PaymentInitRequest(BaseModel):
    plan_type: str  # monthly, quarterly, yearly
    promo_code: Optional[str] = None


class PromoCheckRequest(BaseModel):
    code: str
    plan_type: str


@router.post("/init")
async def init_payment(
    req: PaymentInitRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await create_payment_intent(db, user, req.plan_type, req.promo_code)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error("payment init failed: %s", e)
        raise HTTPException(status_code=503, detail="Оплата временно недоступна, попробуйте позже")


@router.get("/status/{label}")
async def payment_status(
    label: str,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """Client polls this after opening the QuickPay link to learn when the webhook lands."""
    try:
        return await get_payment_status(db, user, label)
    except ValueError:
        raise HTTPException(status_code=404, detail="Платёж не найден")


@router.post("/yumoney/notify")
async def yumoney_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """YuMoney calls this webhook (HTTP notification) after a payment attempt."""
    form_data = await request.form()
    data = dict(form_data)
    result = await process_payment_notification(db, data)
    if not result["ok"]:
        # Invalid signature — never acknowledge, so a forged notification can't be "confirmed" by retrying.
        raise HTTPException(status_code=400, detail="invalid signature")
    # Always 200 for anything with a valid signature — prevents YuMoney retry storms
    # for cases we've already understood (duplicate, ignored, amount mismatch, etc).
    return {"status": "ok", "reason": result["reason"]}


@router.get("/success-page", response_class=HTMLResponse)
async def success_page():
    """Public page YuMoney's successURL points the browser to after payment.

    Purely informational — the client app confirms completion itself via
    GET /payments/status/{label} polling, independent of whether the user
    actually returns to this page.
    """
    return HTMLResponse(_PAYMENT_SUCCESS_HTML)


_PAYMENT_SUCCESS_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Silent VPN — Оплата принята</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:#0a0a0a;font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:16px}
  .card{background:#111;border:1px solid #222;border-radius:16px;padding:48px 40px;max-width:480px;width:100%;text-align:center}
  .icon{width:72px;height:72px;background:#22c55e22;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:32px;color:#22c55e}
  .brand{color:#fff;font-size:13px;font-weight:700;letter-spacing:3px;margin-bottom:32px;opacity:0.5}
  h1{color:#fff;font-size:22px;font-weight:700;margin-bottom:16px}
  p{color:#888;font-size:15px;line-height:1.7}
  .hint{margin-top:24px;color:#555;font-size:13px}
</style>
</head>
<body>
<div class="card">
  <div class="brand">SILENT VPN</div>
  <div class="icon">&#10003;</div>
  <h1>Оплата принята</h1>
  <p>Подписка будет активирована автоматически в течение минуты — вернитесь в приложение.</p>
  <p class="hint">Можно закрыть эту страницу.</p>
</div>
</body>
</html>"""


@router.post("/promo/check")
async def check_promo(
    req: PromoCheckRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime
    result = await db.execute(
        select(PromoCode).where(
            PromoCode.code == req.code.upper(),
            PromoCode.is_active == True,
        )
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise HTTPException(status_code=404, detail="Промокод не найден или уже использован")
    if promo.use_count >= promo.max_uses:
        raise HTTPException(status_code=400, detail="Промокод исчерпан")
    if promo.expires_at and promo.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Промокод истёк")

    price_map = {
        "monthly": settings.PRICE_MONTHLY,
        "quarterly": settings.PRICE_QUARTERLY,
        "yearly": settings.PRICE_YEARLY,
    }
    original = price_map.get(req.plan_type, 0)
    discounted = round(original * (1 - promo.discount_percent / 100), 2)

    return {
        "code": promo.code,
        "discount_percent": promo.discount_percent,
        "extra_days": promo.extra_days,
        "original_price": original,
        "discounted_price": discounted,
    }


@router.get("/plans")
async def get_plans():
    return [
        {"id": "monthly", "name": "Месяц", "price": settings.PRICE_MONTHLY, "days": 30},
        {"id": "quarterly", "name": "3 месяца", "price": settings.PRICE_QUARTERLY, "days": 90},
        {"id": "yearly", "name": "Год", "price": settings.PRICE_YEARLY, "days": 365},
    ]
