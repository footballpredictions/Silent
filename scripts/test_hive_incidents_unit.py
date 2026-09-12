"""Unit tests: hive incident timestamp coercion + soft flap (no DB)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from app.services.hive_incidents import (  # noqa: E402
    _as_utc_dt,
    _is_soft_network_noise,
    _row_to_public,
    reset_soft_flap_state,
    should_persist_after_clear,
    soft_flap_allows,
)


def test_iso_string_becomes_datetime():
    dt = _as_utc_dt("2026-08-16T06:54:14.826730+00:00")
    assert isinstance(dt, datetime)
    assert dt.tzinfo is not None
    assert dt.year == 2026
    assert dt.month == 8
    assert dt.day == 16


def test_zulu_iso_parsed():
    dt = _as_utc_dt("2026-08-16T06:54:14Z")
    assert dt.tzinfo is not None


def test_datetime_passthrough():
    src = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
    assert _as_utc_dt(src) == src


def test_public_row_serializes_ts():
    row = _row_to_public(
        {
            "ts": datetime(2026, 8, 16, 6, 54, 14, tzinfo=timezone.utc),
            "severity": "warning",
            "source": "cell-agent.status",
            "message": "timeout",
            "checks": ["a", "b"],
        }
    )
    assert isinstance(row["ts"], str)
    assert "2026-08-16" in row["ts"]
    assert row["checks"] == ["a", "b"]


def test_clear_skips_stale_persist_queue():
    cleared = "2026-08-21T09:11:29+00:00"
    assert should_persist_after_clear("2026-08-21T09:11:27+00:00", cleared) is False
    assert should_persist_after_clear("2026-08-21T09:12:00+00:00", cleared) is True
    assert should_persist_after_clear("2026-08-21T09:11:27+00:00", None) is True
    assert should_persist_after_clear("2026-08-21T09:11:27+00:00", "") is True


def test_soft_flap_needs_three_then_renotify():
    reset_soft_flap_state()
    key = "soft|cell-agent.status|Сота 2|1.2.3.4|status-unreachable"
    t0 = 1_000_000.0
    assert soft_flap_allows(key, now=t0) is False
    assert soft_flap_allows(key, now=t0 + 30) is False
    assert soft_flap_allows(key, now=t0 + 60) is True
    assert soft_flap_allows(key, now=t0 + 120) is False
    assert soft_flap_allows(key, now=t0 + 3600) is False
    assert soft_flap_allows(key, now=t0 + 6 * 3600 + 10) is False
    assert soft_flap_allows(key, now=t0 + 6 * 3600 + 20) is False
    # last_notified был t0+60 → порог renotify = t0+60+6h
    assert soft_flap_allows(key, now=t0 + 60 + 6 * 3600 + 1) is True


def test_agent_upgrade_empty_message_is_soft():
    assert _is_soft_network_noise("hive.agent-upgrade", "Auto-upgrade cell-agent failed:") is True
    assert _is_soft_network_noise("hive.agent-upgrade", "") is True


if __name__ == "__main__":
    test_iso_string_becomes_datetime()
    test_zulu_iso_parsed()
    test_datetime_passthrough()
    test_public_row_serializes_ts()
    test_clear_skips_stale_persist_queue()
    test_soft_flap_needs_three_then_renotify()
    test_agent_upgrade_empty_message_is_soft()
    print("ok")
