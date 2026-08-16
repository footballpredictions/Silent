"""Unit tests: hive incident timestamp coercion (no DB)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from app.services.hive_incidents import _as_utc_dt, _row_to_public  # noqa: E402


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


if __name__ == "__main__":
    test_iso_string_becomes_datetime()
    test_zulu_iso_parsed()
    test_datetime_passthrough()
    test_public_row_serializes_ts()
    print("ok")
