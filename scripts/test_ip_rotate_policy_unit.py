"""Автосмена IP: dry-run, без API хостера, без wdtt."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.availability_model import TARGET_QUEEN, TargetSnapshot  # noqa: E402
from ai.ip_rotate_policy import (  # noqa: E402
    ACTION_DRY_RUN,
    ACTION_HOLD,
    CONFIRM_PATH_FAILURES,
    IP_READERS,
    IpRotateInput,
    build_ip_plan,
    decide_ip_rotate,
    hoster_for_ip,
    vps_id_for_ip,
)


def _inp(**kw) -> IpRotateInput:
    data = dict(
        node_id="89.125.188.100",
        node_name="Улей",
        current_ip="89.125.188.100",
        role=TARGET_QUEEN,
        dry_run=True,
        paid_enabled=False,
        rf_coverage_ok=True,
        service_healthy=True,
        path_failures=CONFIRM_PATH_FAILURES,
        replacements_24h=0,
        budget_known=True,
        max_price=10.0,
        allowlist=("89.125.188.100",),
    )
    data.update(kw)
    return IpRotateInput(**data)


def test_unknown_hoster_never_purchases():
    d = decide_ip_rotate(
        _inp(
            node_id="203.0.113.9",
            current_ip="203.0.113.9",
            hoster_id="",
            allowlist=(),
            budget_known=True,
            max_price=10.0,
            paid_enabled=True,
            dry_run=False,
        )
    )
    assert d.action == ACTION_HOLD
    assert d.reason == "hoster_unknown"
    assert d.executed is False


def test_no_rf_coverage_blocks_purchase():
    d = decide_ip_rotate(_inp(rf_coverage_ok=False, hoster_id="hostkey"))
    assert d.reason == "no_rf_coverage"
    assert d.executed is False


def test_unconfirmed_path_does_not_buy():
    d = decide_ip_rotate(_inp(path_failures=1, hoster_id="hostkey"))
    assert d.reason == "not_confirmed"


def test_unknown_budget_stops():
    d = decide_ip_rotate(_inp(hoster_id="hostkey", budget_known=False, max_price=None))
    assert d.reason == "budget_unknown"


def test_dry_run_even_when_hoster_known():
    d = decide_ip_rotate(_inp(hoster_id="hostkey", paid_enabled=True, dry_run=True))
    assert d.action == ACTION_DRY_RUN
    assert d.executed is False
    assert len(d.readers) == len(IP_READERS)


def test_paid_flag_still_does_not_call_hoster():
    d = decide_ip_rotate(_inp(hoster_id="hostkey", paid_enabled=True, dry_run=False))
    assert d.executed is False
    assert d.action in (ACTION_HOLD, ACTION_DRY_RUN)


def test_hoster_map_onedash():
    assert hoster_for_ip("192.177.26.38") == "onedash"
    assert hoster_for_ip("89.125.188.100") == "onedash"
    assert hoster_for_ip("87.58.213.193") == "onedash"
    assert hoster_for_ip("78.17.74.27") == "onedash"
    assert hoster_for_ip("203.0.113.9") == ""
    assert vps_id_for_ip("89.125.188.100") == 167346
    assert vps_id_for_ip("192.177.26.38") == 315445


def test_onedash_without_change_ip_method_stays_dry_run():
    d = decide_ip_rotate(_inp(hoster_id="onedash", paid_enabled=True, dry_run=False, change_ip_method=""))
    assert d.executed is False
    assert d.action == ACTION_DRY_RUN
    assert d.reason == "change_ip_not_in_api_docs"


def test_build_ip_plan_is_hold_without_budget():
    snap = TargetSnapshot(name="Улей", host="89.125.188.100", role=TARGET_QUEEN)
    plan = build_ip_plan([snap], [], dry_run=True, paid_enabled=False)
    assert plan["executed"] is False
    assert plan["action"] == ACTION_HOLD
    assert plan["readers"]


def test_timeout_request_does_not_retry_purchase():
    """Контракт: контроллер не повторяет платный запрос. Здесь нет клиента хостера."""
    first = decide_ip_rotate(_inp(hoster_id="hostkey", paid_enabled=True, dry_run=False))
    second = decide_ip_rotate(_inp(hoster_id="hostkey", paid_enabled=True, dry_run=False, replacements_24h=1))
    assert first.executed is False
    assert second.reason == "daily_limit"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"ok ({len(tests)} tests)")
