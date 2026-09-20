"""Cell wdtt reports online to 127.0.0.1:8000 (standby). That must reach the queen."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cell-agent"))

from standby_online import (  # noqa: E402
    hive_cell_id_from_manifest,
    should_proxy_internal_online,
)


def test_proxy_online_only_while_queen_is_up():
    assert should_proxy_internal_online(queen_healthy=True) is True
    assert should_proxy_internal_online(queen_healthy=False) is False


def test_standby_handler_forwards_online_to_queen():
    src = (ROOT / "cell-agent" / "standby_runtime.py").read_text(encoding="utf-8")
    start = src.index("async def internal_online")
    end = src.index("async def internal_access", start)
    body = src[start:end]
    assert "should_proxy_internal_online" in body
    assert '_proxy_queen(request, "vpn/internal/online"' in body
    assert "X-Hive-Cell-Id" in body
    assert "wg set" not in body


def test_manifest_cell_id_goes_to_queen_header():
    assert hive_cell_id_from_manifest({"cell_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}) == (
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    assert hive_cell_id_from_manifest({}) == ""
    assert hive_cell_id_from_manifest(None) == ""


def test_status_exposes_live_pubs_for_dashboard_hashes():
    src = (ROOT / "cell-agent" / "standby_runtime.py").read_text(encoding="utf-8")
    assert "def wg_live_pubs" in src
    main = (ROOT / "cell-agent" / "main.py").read_text(encoding="utf-8")
    assert '"wg_live_pubs"' in main


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ok ({len(tests)} tests)")
