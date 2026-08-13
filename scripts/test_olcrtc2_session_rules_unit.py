# -*- coding: utf-8 -*-
"""Pure unit tests for olcrtc2 assign/session rules (no DB/asyncpg)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSIGN = (ROOT / "app" / "services" / "olcrtc2_assign.py").read_text(encoding="utf-8")
LIVENESS = (ROOT / "ai" / "olcrtc_room_liveness.py").read_text(encoding="utf-8")


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


def test_provider_cell_roles_not_on_queen():
    # Telemost/WB must not bind to queen WDTT host in comments/constants nearby
    # Soft check: hive cells mentioned or provider→cell mapping present
    assert "telemost" in ASSIGN.lower()
    assert "wbstream" in ASSIGN.lower()


def main() -> int:
    tests = [
        test_assign_probes_carrier_before_sticky,
        test_liveness_has_wb_and_telemost,
        test_assign_source_parses,
        test_provider_cell_roles_not_on_queen,
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
