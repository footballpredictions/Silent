"""Unit tests: dynamic hive slots (Улей=server1, Сота N=server{N+1})."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from app.services.hive_slots import (  # noqa: E402
    is_manual_server_pin,
    parse_manual_slot,
    slot_for_cell,
    slot_title,
)


def test_slot_for_queen_and_named_cells():
    queen = SimpleNamespace(is_queen=True, name="Улей")
    assert slot_for_cell(queen) == "server1"
    assert slot_for_cell(SimpleNamespace(is_queen=False, name="Сота 1")) == "server2"
    assert slot_for_cell(SimpleNamespace(is_queen=False, name="Сота 2")) == "server3"
    assert slot_for_cell(SimpleNamespace(is_queen=False, name="Сота 3")) == "server4"
    assert slot_for_cell(SimpleNamespace(is_queen=False, name="Сота 10")) == "server11"


def test_unnamed_worker_has_no_fixed_slot():
    assert slot_for_cell(SimpleNamespace(is_queen=False, name="worker-alpha")) == ""


def test_manual_pin_any_server_n():
    assert is_manual_server_pin("server1")
    assert is_manual_server_pin("server4")
    assert is_manual_server_pin("SERVER12")
    assert not is_manual_server_pin("queen")
    assert not is_manual_server_pin("cell:abc")
    assert parse_manual_slot("server4") == 4
    assert slot_title("server4") == "Сервер 4"


if __name__ == "__main__":
    test_slot_for_queen_and_named_cells()
    test_unnamed_worker_has_no_fixed_slot()
    test_manual_pin_any_server_n()
    print("ok")
