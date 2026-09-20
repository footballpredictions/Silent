"""Unit: /payments/plans default hides 5-device tiers from old clients."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.shop_catalog import build_shop_plans  # noqa: E402


def test_get_plans_default_only_three_device():
    out = build_shop_plans(include_five_device=False)
    assert len(out) == 3
    assert [p["id"] for p in out] == ["monthly", "two_months", "quarterly"]
    assert all(p.get("devices") == 3 for p in out)


def test_get_plans_all_includes_five_device():
    out = build_shop_plans(include_five_device=True)
    assert len(out) == 6
    ids = [p["id"] for p in out]
    assert "monthly_5" in ids
    assert "quarterly_5" in ids


if __name__ == "__main__":
    test_get_plans_default_only_three_device()
    test_get_plans_all_includes_five_device()
    print("ok")
