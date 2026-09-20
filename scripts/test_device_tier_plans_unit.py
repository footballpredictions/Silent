"""Unit: тарифы 3/5 устройств — срок плана и лимит слотов."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.subscription_kinds import (  # noqa: E402
    duration_plan_key,
    devices_for_plan,
    plan_expires_at,
    user_matches_subscription_filter,
)


def test_duration_plan_key_strips_device_suffix():
    assert duration_plan_key("monthly") == "monthly"
    assert duration_plan_key("monthly_5") == "monthly"
    assert duration_plan_key("two_months_5") == "two_months"
    assert duration_plan_key("quarterly_5") == "quarterly"
    assert duration_plan_key("TRIAL") == "trial"
    assert duration_plan_key(None) == ""


def test_devices_for_plan():
    assert devices_for_plan(None) == 3
    assert devices_for_plan("trial") == 3
    assert devices_for_plan("monthly") == 3
    assert devices_for_plan("two_months") == 3
    assert devices_for_plan("quarterly") == 3
    assert devices_for_plan("monthly_5") == 5
    assert devices_for_plan("two_months_5") == 5
    assert devices_for_plan("quarterly_5") == 5
    assert devices_for_plan("MONTHLY_5") == 5


def test_plan_expires_at_same_for_5_device_plans():
    base = datetime(2026, 9, 7, 12, 0, 0)
    assert plan_expires_at(base, "monthly_5") == plan_expires_at(base, "monthly")
    assert plan_expires_at(base, "two_months_5") == plan_expires_at(base, "two_months")
    assert plan_expires_at(base, "quarterly_5") == plan_expires_at(base, "quarterly")


def test_admin_filter_months_include_5_device():
    assert user_matches_subscription_filter(
        mode="monthly", best_kind="paid", best_plan="monthly_5"
    )
    assert user_matches_subscription_filter(
        mode="two_months", best_kind="paid", best_plan="two_months_5"
    )
    assert user_matches_subscription_filter(
        mode="quarterly", best_kind="paid", best_plan="quarterly_5"
    )
    assert not user_matches_subscription_filter(
        mode="monthly", best_kind="paid", best_plan="quarterly_5"
    )


if __name__ == "__main__":
    test_duration_plan_key_strips_device_suffix()
    test_devices_for_plan()
    test_plan_expires_at_same_for_5_device_plans()
    test_admin_filter_months_include_5_device()
    print("ok")
