"""Pure subscription kind helpers (no FastAPI) — dashboard / filters."""
from __future__ import annotations

import calendar
import math
from datetime import datetime, timedelta

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

# Месячные планы: календарные месяцы (7.09 → 7.11 для 2 мес.), не 60×24ч.
PLAN_CALENDAR_MONTHS = {
    "monthly": 1,
    "two_months": 2,
    "quarterly": 3,
    "half_year": 6,
    "yearly": 12,
}
PLAN_FIXED_DAYS = {
    "three_days": 3,
    "unlimited": 36500,  # ~100 лет
}

# Старая схема срока (до 2026-09-07): ровно N суток, не календарные месяцы.
LEGACY_PLAN_FIXED_DAYS = {
    "monthly": 30,
    "two_months": 60,
    "quarterly": 90,
    "half_year": 180,
    "yearly": 365,
}

# Naive UTC: после рестарта api в деплое календарных месяцев (≈15:15 МСК).
CALENDAR_MONTHS_DEPLOY_CUTOFF_UTC = datetime(2026, 9, 7, 12, 15, 0)


def add_calendar_months(dt: datetime, months: int) -> datetime:
    """Календарные месяцы по реальному году (в т.ч. високосному).

    Правило как у банков/подписок: то же число через N месяцев.
    Если такого числа нет — последний день целевого месяца:
      31 янв 2026 + 1 мес → 28 фев 2026
      31 янв 2024 + 1 мес → 29 фев 2024 (високосный)
      31 мар + 1 мес → 30 апр
      29 фев 2024 + 12 мес → 28 фев 2025
    """
    if months == 0:
        return dt
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    # monthrange(year, month) → (weekday, days_in_month); days учитывает leap year
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def plan_expires_at(base: datetime, plan_type: str) -> datetime:
    """Срок окончания плана от base (обычно now или текущий expires_at при продлении)."""
    plan = (plan_type or "").strip().lower()
    if plan in PLAN_FIXED_DAYS:
        return base + timedelta(days=PLAN_FIXED_DAYS[plan])
    if plan in PLAN_CALENDAR_MONTHS:
        return add_calendar_months(base, PLAN_CALENDAR_MONTHS[plan])
    # неизвестный / legacy — как месяц
    return add_calendar_months(base, 1)


def bonus_period_expires(base: datetime, days: int) -> datetime:
    """Реферальный/бонусный срок: 30 дней → 1 календарный месяц; иначе кратно 30 → N мес.; иначе сутки."""
    n = int(days or 0)
    if n <= 0:
        return base
    if n % 30 == 0:
        return add_calendar_months(base, n // 30)
    return base + timedelta(days=n)


# При оплате не продлевать купленный план «поверх» бесплатного рефа/trial —
# иначе 3 мес. от 27.08 выглядят как до 25.12 (база = конец рефа +90 суток).
PAID_STACK_SKIP_PLANS = frozenset({TRIAL_PLAN, REFERRAL_PLAN, TEST_PLAN})


def paid_subscription_stack_base(
    now: datetime,
    active_plan_expires: list[tuple[str, datetime | None]],
) -> datetime:
    """База для новой оплаченной/выданной подписки: max(now, expires платных), без referral/trial/test."""
    base = now
    for plan_type, expires_at in active_plan_expires:
        plan = (plan_type or "").strip().lower()
        if plan in PAID_STACK_SKIP_PLANS or expires_at is None:
            continue
        exp = expires_at.replace(tzinfo=None) if getattr(expires_at, "tzinfo", None) else expires_at
        if exp > base:
            base = exp
    return base


def suggest_calendar_expires_fix(
    *,
    plan_type: str,
    started_at: datetime,
    expires_at: datetime,
    grant_cutoff: datetime | None = None,
) -> datetime | None:
    """Новый expires_at для строки «started + N суток» (старая схема); иначе None.

    Fail-safe: не укорачивает; не трогает выдачи с started_at >= cutoff;
    идемпотентен (повторный прогон не двигает уже календарные сроки).
    Стек «поверх чужого expires» не трогаем — там base ≠ started_at.
    """
    plan = (plan_type or "").strip().lower()
    n = LEGACY_PLAN_FIXED_DAYS.get(plan)
    if n is None or plan not in PLAN_CALENDAR_MONTHS:
        return None
    if started_at is None or expires_at is None:
        return None

    cutoff = grant_cutoff or CALENDAR_MONTHS_DEPLOY_CUTOFF_UTC
    started = started_at.replace(tzinfo=None) if started_at.tzinfo else started_at
    expires = expires_at.replace(tzinfo=None) if expires_at.tzinfo else expires_at
    if started >= cutoff:
        return None

    # Уже календарь от started — не трогаем
    if abs((plan_expires_at(started, plan) - expires).total_seconds()) <= 2:
        return None

    # Только классика: expires = started + N суток (не стек)
    if abs((started + timedelta(days=n) - expires).total_seconds()) > 2:
        return None

    new_exp = plan_expires_at(started, plan)
    if new_exp <= expires + timedelta(seconds=2):
        return None
    return new_exp


def compute_days_left(expires_at: datetime, now: datetime | None = None) -> int:
    """Календарные дни «включичительно»: при 3-дневном триале сразу 3, в последний день 1.

    timedelta.days обрезает вниз (72ч−1с → 2), из‑за этого клиент писал «осталось 2»
    в момент выдачи и «0» в последний день.
    """
    now = now or datetime.utcnow()
    secs = (expires_at - now).total_seconds()
    if secs <= 0:
        return 0
    return max(1, math.ceil(secs / 86400))


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
