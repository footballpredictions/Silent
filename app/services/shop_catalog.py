"""Shop plan catalog for GET /payments/plans (no DB imports)."""
from __future__ import annotations

from app.config import settings


def build_shop_plans(*, include_five_device: bool = False) -> list[dict]:
    """Каталог магазина.

    include_five_device=False — только 3 устройства (старые клиенты до релиза 3/5).
    """
    plans = [
        {"id": "monthly", "name": "Месяц", "price": settings.PRICE_MONTHLY, "days": 30, "devices": 3},
        {"id": "two_months", "name": "2 месяца", "price": settings.PRICE_TWO_MONTHS, "days": 60, "devices": 3},
        {"id": "quarterly", "name": "3 месяца", "price": settings.PRICE_QUARTERLY, "days": 90, "devices": 3},
    ]
    if not include_five_device:
        return plans
    plans.extend(
        [
            {"id": "monthly_5", "name": "Месяц", "price": settings.PRICE_MONTHLY_5, "days": 30, "devices": 5},
            {"id": "two_months_5", "name": "2 месяца", "price": settings.PRICE_TWO_MONTHS_5, "days": 60, "devices": 5},
            {"id": "quarterly_5", "name": "3 месяца", "price": settings.PRICE_QUARTERLY_5, "days": 90, "devices": 5},
        ]
    )
    return plans
