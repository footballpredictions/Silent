"""Unit: dashboard subscription kind classification + filter rules."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.subscription_kinds import (  # noqa: E402
    classify_subscription_kind,
    user_matches_subscription_filter,
    WITH_SUB_KINDS,
)


def test_classify_paid_granted_referral_trial() -> None:
    assert classify_subscription_kind("monthly", 199) == "paid"
    assert classify_subscription_kind("yearly", 0.01) == "paid"
    assert classify_subscription_kind("monthly", 0) == "granted"
    assert classify_subscription_kind("unlimited", 0) == "granted"
    assert classify_subscription_kind("referral_bonus", 0) == "referral"
    assert classify_subscription_kind("referral_bonus", 10) == "referral"
    assert classify_subscription_kind("trial", 0) == "trial"
    assert classify_subscription_kind("trial", 10) == "trial"
    assert classify_subscription_kind("test", 0) == "other"


def test_filter_semantics_best_only() -> None:
    assert user_matches_subscription_filter(mode="with_sub", best_kind="paid")
    assert user_matches_subscription_filter(mode="with_sub", best_kind="granted")
    assert user_matches_subscription_filter(mode="with_sub", best_kind="referral")
    assert not user_matches_subscription_filter(mode="with_sub", best_kind="trial")

    # Месяцы — только если best = купленный этот план
    assert user_matches_subscription_filter(
        mode="monthly", best_kind="paid", best_plan="monthly"
    )
    assert not user_matches_subscription_filter(
        mode="monthly", best_kind="referral", best_plan="referral_bonus"
    )
    # Купил месяц, потом выдали unlimited → best=granted → не в «Купили 1 мес.»
    assert not user_matches_subscription_filter(
        mode="monthly", best_kind="granted", best_plan="unlimited"
    )
    # Купил месяц, потом длиннее реф.бонус → не в месяцах
    assert not user_matches_subscription_filter(
        mode="monthly",
        best_kind="referral",
        best_plan="referral_bonus",
        live_plans_paid=frozenset({"monthly"}),
    )

    assert user_matches_subscription_filter(mode="granted", best_kind="granted")
    assert not user_matches_subscription_filter(mode="granted", best_kind="referral")
    assert user_matches_subscription_filter(mode="referrals", best_kind="referral")
    assert user_matches_subscription_filter(mode="trial", best_kind="trial")
    assert WITH_SUB_KINDS == frozenset({"paid", "granted", "referral"})


if __name__ == "__main__":
    test_classify_paid_granted_referral_trial()
    test_filter_semantics_best_only()
    print("OK")
