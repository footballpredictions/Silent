"""Unit: subscription list filter modes for admin Подписки."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.subscription_kinds import (  # noqa: E402
    normalize_subscription_filter,
    SUBSCRIPTION_FILTER_MODES,
    user_matches_subscription_filter,
    can_buy_paid_plan,
    is_active_trial_row,
)


def test_normalize_filters():
    assert normalize_subscription_filter("all") == "all"
    assert normalize_subscription_filter("ACTIVE") == "with_sub"
    assert normalize_subscription_filter("with_sub") == "with_sub"
    assert normalize_subscription_filter("monthly") == "monthly"
    assert normalize_subscription_filter("two_months") == "two_months"
    assert normalize_subscription_filter("quarterly") == "quarterly"
    assert normalize_subscription_filter("granted") == "granted"
    assert normalize_subscription_filter("inactive") == "inactive"
    assert normalize_subscription_filter("unpaid") == "unpaid"
    assert normalize_subscription_filter("referrals") == "referrals"
    assert normalize_subscription_filter("trial") == "trial"
    assert normalize_subscription_filter("nope") == "all"
    assert normalize_subscription_filter(None) == "all"
    assert "with_sub" in SUBSCRIPTION_FILTER_MODES


def test_months_best_paid_only():
    assert user_matches_subscription_filter(
        mode="monthly", best_kind="paid", best_plan="monthly"
    )
    assert not user_matches_subscription_filter(
        mode="monthly", best_kind="granted", best_plan="unlimited"
    )
    assert not user_matches_subscription_filter(
        mode="two_months", best_kind="referral", best_plan="referral_bonus"
    )
    assert user_matches_subscription_filter(
        mode="quarterly", best_kind="paid", best_plan="quarterly"
    )
    assert not user_matches_subscription_filter(
        mode="quarterly", best_kind="paid", best_plan="monthly"
    )


def test_shop_open_on_trial_and_when_inactive():
    assert can_buy_paid_plan(is_active=False, plan_type=None)
    assert can_buy_paid_plan(is_active=True, plan_type="trial")
    assert can_buy_paid_plan(is_active=True, plan_type="TRIAL")
    assert not can_buy_paid_plan(is_active=True, plan_type="monthly")
    assert not can_buy_paid_plan(is_active=True, plan_type="three_days")
    assert not can_buy_paid_plan(is_active=True, plan_type="unlimited")


def test_end_trial_selects_only_live_trial():
    assert is_active_trial_row("trial", "active")
    assert not is_active_trial_row("trial", "cancelled")
    assert not is_active_trial_row("three_days", "active")
    assert not is_active_trial_row("monthly", "active")


def test_trial_is_not_a_grantable_paid_plan():
    from app.services.subscription_kinds import PAID_OR_GRANTED_PLANS, TRIAL_PLAN

    assert TRIAL_PLAN not in PAID_OR_GRANTED_PLANS
    assert "three_days" in PAID_OR_GRANTED_PLANS


if __name__ == "__main__":
    test_normalize_filters()
    test_months_best_paid_only()
    test_shop_open_on_trial_and_when_inactive()
    test_end_trial_selects_only_live_trial()
    test_trial_is_not_a_grantable_paid_plan()
    print("ok")
