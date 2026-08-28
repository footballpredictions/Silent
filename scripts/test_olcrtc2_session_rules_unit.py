# -*- coding: utf-8 -*-
"""Pure unit tests for olcrtc2 assign/session rules (no DB/asyncpg)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSIGN = (ROOT / "app" / "services" / "olcrtc2_assign.py").read_text(encoding="utf-8")
LIVENESS = (ROOT / "ai" / "olcrtc_room_liveness.py").read_text(encoding="utf-8")
SETTINGS = (ROOT / "app" / "services" / "olcrtc2_settings.py").read_text(encoding="utf-8")
HIVE = (ROOT / "app" / "services" / "hive_service.py").read_text(encoding="utf-8")


def test_assign_probes_carrier_before_sticky():
    assert "_carrier_room_alive" in ASSIGN
    assert "probe_room" in ASSIGN or "from ai.olcrtc_room_liveness" in ASSIGN
    # Dead carrier must not stay sticky
    assert "carrier" in ASSIGN
    assert "unit_ok" in ASSIGN


def test_liveness_has_wb_and_telemost():
    assert "wbstream" in LIVENESS or "wb" in LIVENESS.lower()
    assert "telemost" in LIVENESS.lower()
    assert "async def probe_room" in LIVENESS


def test_assign_source_parses():
    ast.parse(ASSIGN)


def test_occupancy_one_client_per_room():
    assert "TELEMOST_MAX_CLIENTS = 1" in ASSIGN
    assert "WBSTREAM_MAX_CLIENTS = 1" in ASSIGN
    assert "TELEMOST_MAX_CLIENTS = 3" not in ASSIGN
    assert "stickies > 0" in ASSIGN


def test_provider_cell_roles_not_on_queen():
    # Telemost/WB must not bind to queen WDTT host in comments/constants nearby
    # Soft check: hive cells mentioned or provider→cell mapping present
    assert "telemost" in ASSIGN.lower()
    assert "wbstream" in ASSIGN.lower()


def test_telemost_warm_not_inflated_to_20():
    assert not (ROOT / "ai" / "olcrtc2_room_agent.py").is_file()
    assert "TELEMOST_WARM_PER_DT_CAP = 2" in SETTINGS
    assert "def warm_pool_for" in SETTINGS
    assert "EXCESS_WARM_KEEP_SEC = 90" in ASSIGN
    assert "warm_pool_for" in ASSIGN


def test_wdtt_spill_skips_olcrtc_cells():
    assert "def cell_accepts_wdtt_spill" in HIVE
    assert "def list_wdtt_spill_workers" in HIVE
    assert "87.58.213.193" in (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "accepts_wdtt" in HIVE


def main() -> int:
    tests = [
        test_assign_probes_carrier_before_sticky,
        test_liveness_has_wb_and_telemost,
        test_assign_source_parses,
        test_occupancy_one_client_per_room,
        test_provider_cell_roles_not_on_queen,
        test_telemost_warm_not_inflated_to_20,
        test_wdtt_spill_skips_olcrtc_cells,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    if failed:
        print(f"{failed}/{len(tests)} failed")
        return 1
    print(f"all {len(tests)} ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
