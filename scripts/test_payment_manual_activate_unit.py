"""Unit: ручная выдача pending YuMoney, если webhook не дошёл."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.payment_manual_activate import can_manual_activate  # noqa: E402


def test_pending_unapplied_can_be_granted():
    assert can_manual_activate(status="pending", applied=False, is_admin=False)
    assert can_manual_activate(status="completed", applied=False, is_admin=False)
    assert can_manual_activate(status="expired", applied=False, is_admin=False)


def test_already_applied_or_admin_cannot():
    assert not can_manual_activate(status="pending", applied=True, is_admin=False)
    assert not can_manual_activate(status="pending", applied=False, is_admin=True)
    assert not can_manual_activate(status="failed", applied=False, is_admin=False)


if __name__ == "__main__":
    test_pending_unapplied_can_be_granted()
    test_already_applied_or_admin_cannot()
    print("ok")
