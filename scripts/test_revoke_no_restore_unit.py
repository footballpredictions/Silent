"""Unit: admin revoke must not be resurrected by restore-previous helpers."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.subscription_kinds import mark_subscription_admin_revoked  # noqa: E402


def test_revoked_paid_plan_not_restorable_by_expires_gate():
    now = datetime(2026, 9, 20, 12, 0, 0)
    sub = SimpleNamespace(
        status="active",
        plan_type="monthly",
        expires_at=now + timedelta(days=20),
    )
    mark_subscription_admin_revoked(sub, now)
    assert sub.status == "cancelled"
    assert sub.expires_at == now
    # Mirror _restore_previous_subscription filter: expires_at > now
    assert not (sub.expires_at > now)


def test_end_trial_clamp_blocks_restore():
    now = datetime(2026, 9, 20, 12, 0, 0)
    trial = SimpleNamespace(
        status="active",
        plan_type="trial",
        expires_at=now + timedelta(days=2),
    )
    mark_subscription_admin_revoked(trial, now)
    assert trial.expires_at == now
    assert not (trial.expires_at > now)


if __name__ == "__main__":
    test_revoked_paid_plan_not_restorable_by_expires_gate()
    test_end_trial_clamp_blocks_restore()
    print("ok")
