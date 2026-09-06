"""Unit: dashboard subscription kind classification."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.subscription_kinds import classify_subscription_kind  # noqa: E402


def test_classify_paid_granted_trial() -> None:
    assert classify_subscription_kind("monthly", 199) == "paid"
    assert classify_subscription_kind("yearly", 0.01) == "paid"
    assert classify_subscription_kind("monthly", 0) == "granted"
    assert classify_subscription_kind("unlimited", 0) == "granted"
    assert classify_subscription_kind("referral_bonus", 0) == "granted"
    assert classify_subscription_kind("trial", 0) == "trial"
    assert classify_subscription_kind("trial", 10) == "trial"
    assert classify_subscription_kind("test", 0) == "other"


if __name__ == "__main__":
    test_classify_paid_granted_trial()
    print("OK")
