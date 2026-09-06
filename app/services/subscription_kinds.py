"""Pure subscription kind helpers (no FastAPI) — dashboard / filters."""
from __future__ import annotations

TRIAL_PLAN = "trial"
TEST_PLAN = "test"
REFERRAL_PLAN = "referral_bonus"

# Фильтры меню «Подписки» (query ?filter=)
SUBSCRIPTION_FILTER_MODES = frozenset({
    "all",
    "with_sub",
    "monthly",
    "two_months",
    "quarterly",
    "granted",
    "inactive",
    "unpaid",
    "referrals",
    "trial",
    # legacy alias
    "active",
})

# Планы, которые админ может выдать (не trial / test / referral_bonus)
PAID_OR_GRANTED_PLANS = (
    "three_days",
    "monthly",
    "two_months",
    "quarterly",
    "half_year",
    "yearly",
    "unlimited",
)

# Живой доступ «с подпиской»: покупки + выданные админом + реф.бонус (без trial/test)
WITH_SUB_KINDS = frozenset({"paid", "granted", "referral"})


def normalize_subscription_filter(raw: str | None) -> str:
    mode = (raw or "all").strip().lower()
    if mode == "active":
        return "with_sub"
    if mode not in SUBSCRIPTION_FILTER_MODES:
        return "all"
    return mode


def classify_subscription_kind(plan_type: str | None, amount_paid: float | int | None) -> str:
    """paid | granted | referral | trial | other — одна категория на живой план.

    paid: покупка (YuMoney), amount_paid > 0
    granted: выдал админ (amount_paid=0 на обычном плане)
    referral: реферальный бонус (plan=referral_bonus) — только в «Рефералы» / «Все» / «С подпиской»
    trial: пробный период
    """
    plan = (plan_type or "").strip().lower()
    amount = float(amount_paid or 0)
    if plan == TRIAL_PLAN:
        return "trial"
    if plan == TEST_PLAN:
        return "other"
    if plan == REFERRAL_PLAN:
        return "referral"
    if amount > 0:
        return "paid"
    return "granted"


def filter_mode_for_kind(kind: str) -> str | None:
    """Какой пункт меню «Подписки» соответствует kind (кроме месяцев)."""
    if kind == "paid":
        return None  # месяцы — отдельно по plan_type + amount>0
    if kind == "granted":
        return "granted"
    if kind == "referral":
        return "referrals"
    if kind == "trial":
        return "trial"
    return None


def user_matches_subscription_filter(
    *,
    mode: str,
    best_kind: str | None,
    best_plan: str | None = None,
    live_plans_paid: frozenset[str] | set[str] = (),
    referred: bool = False,
    has_unpaid: bool = False,
    has_vpn_access: bool = False,
) -> bool:
    """Единые правила фильтра списка Подписок (для unit-тестов и документации).

    best_kind / best_plan — classify и plan_type самого долгого живого плана (без test).
    live_plans_paid — устарело; месяцы смотрят только best_plan + paid.
    """
    mode = normalize_subscription_filter(mode)
    if mode == "all":
        return True
    if mode == "with_sub":
        return best_kind in WITH_SUB_KINDS
    if mode == "monthly":
        return best_kind == "paid" and best_plan == "monthly"
    if mode == "two_months":
        return best_kind == "paid" and best_plan == "two_months"
    if mode == "quarterly":
        return best_kind == "paid" and best_plan == "quarterly"
    if mode == "granted":
        return best_kind == "granted"
    if mode == "trial":
        return best_kind == "trial"
    if mode == "referrals":
        return best_kind == "referral"
    if mode == "inactive":
        return not has_vpn_access
    if mode == "unpaid":
        return has_unpaid
    return True
