"""Pure subscription kind helpers (no FastAPI) — dashboard / filters."""
from __future__ import annotations

TRIAL_PLAN = "trial"
TEST_PLAN = "test"


def classify_subscription_kind(plan_type: str | None, amount_paid: float | int | None) -> str:
    """paid | granted | trial | other — для дашборда.

    paid: покупка (YuMoney), amount_paid > 0
    granted: выдал админ (amount_paid=0) + бесплатные бонусы (referral и т.п.)
    trial: пробный период
    """
    plan = (plan_type or "").strip().lower()
    amount = float(amount_paid or 0)
    if plan == TRIAL_PLAN:
        return "trial"
    if plan == TEST_PLAN:
        return "other"
    if amount > 0:
        return "paid"
    return "granted"
