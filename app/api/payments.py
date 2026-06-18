from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models import User, PromoCode
from app.core.deps import get_verified_user
from app.services.payment_service import create_payment_intent, process_payment_notification
from app.config import settings

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


@router.post("/yumoney/notify")
async def yumoney_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """YuMoney calls this webhook after successful payment."""
    form_data = await request.form()
    data = dict(form_data)
    success = await process_payment_notification(db, data)
    # YuMoney expects 200 response
    return {"status": "ok" if success else "ignored"}


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
