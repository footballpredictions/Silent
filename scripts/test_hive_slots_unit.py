"""Unit tests: dynamic hive slots (Улей=server1, Сота N=server{N+1})."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from app.services.hive_slots import (  # noqa: E402
    assign_online_to_cell_id,
    device_on_node,
    is_manual_server_pin,
    node_online_shown,
    node_title_for_slot,
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
    assert node_title_for_slot("server1") == "Улей"
    assert node_title_for_slot("server2") == "Сота 1"
    assert node_title_for_slot("server3") == "Сота 2"


def test_node_title_for_slot():
    assert node_title_for_slot(None) == "Улей"
    assert node_title_for_slot("server1") == "Улей"
    assert node_title_for_slot("server2") == "Сота 1"


def test_cell1_slot_is_server2_for_manifest():
    assert slot_for_cell(SimpleNamespace(is_queen=False, name="Сота 1")) == "server2"
    assert slot_for_cell(SimpleNamespace(is_queen=False, name="Сота 2")) == "server3"


def test_device_on_node_default_server1_stays_on_cell():
    queen_id, cell1_id = "q", "c1"
    # Default server1, но cell_id на соте — это сота, не Улей.
    assert not device_on_node(
        cell_is_queen=True, cell_id=queen_id, cell_slot="server1",
        device_cell_id=cell1_id, preferred="server1",
    )
    assert device_on_node(
        cell_is_queen=False, cell_id=cell1_id, cell_slot="server2",
        device_cell_id=cell1_id, preferred="server1",
    )
    # Явный pin server2 важнее cell_id Улья.
    assert device_on_node(
        cell_is_queen=False, cell_id=cell1_id, cell_slot="server2",
        device_cell_id=queen_id, preferred="server2",
    )
    assert not device_on_node(
        cell_is_queen=True, cell_id=queen_id, cell_slot="server1",
        device_cell_id=queen_id, preferred="server2",
    )
    # Реально на Улье.
    assert device_on_node(
        cell_is_queen=True, cell_id=queen_id, cell_slot="server1",
        device_cell_id=queen_id, preferred="server1",
    )


def test_node_online_shown_is_db_only():
    assert node_online_shown(is_queen=True, db_online=71, wg_live=95, wg_live_known=71) == 71
    assert node_online_shown(is_queen=True, db_online=71, wg_live=95, wg_live_known=None) == 71
    assert node_online_shown(is_queen=False, db_online=4, wg_live=9, wg_live_known=None) == 4


def test_assign_online_unique_partition():
    queen, c1, c2 = "q", "c1", "c2"
    known = {queen, c1, c2}
    slots = {"server1": queen, "server2": c1, "server3": c2}
    assert assign_online_to_cell_id(
        device_cell_id=queen, preferred="server2", queen_id=queen,
        slot_to_id=slots, known_ids=known,
    ) == c1
    assert assign_online_to_cell_id(
        device_cell_id=c1, preferred="server1", queen_id=queen,
        slot_to_id=slots, known_ids=known,
    ) == c1
    assert assign_online_to_cell_id(
        device_cell_id=queen, preferred="server1", queen_id=queen,
        slot_to_id=slots, known_ids=known,
    ) == queen
    assert assign_online_to_cell_id(
        device_cell_id="gone", preferred="server1", queen_id=queen,
        slot_to_id=slots, known_ids=known,
    ) == queen
    assert assign_online_to_cell_id(
        device_cell_id=c1, preferred="server3", queen_id=queen,
        slot_to_id=slots, known_ids=known,
    ) == c2
    # Сумма карточек = число устройств.
    rows = [
        (queen, "server1"),
        (c1, "server1"),
        (c1, "server2"),
        (queen, "server3"),
        (None, "server1"),
    ]
    counts = {queen: 0, c1: 0, c2: 0}
    for cell_id, pref in rows:
        nid = assign_online_to_cell_id(
            device_cell_id=cell_id, preferred=pref, queen_id=queen,
            slot_to_id=slots, known_ids=known,
        )
        counts[nid] += 1
    assert counts[queen] + counts[c1] + counts[c2] == len(rows)
    assert counts == {queen: 2, c1: 2, c2: 1}


if __name__ == "__main__":
    test_slot_for_queen_and_named_cells()
    test_unnamed_worker_has_no_fixed_slot()
    test_manual_pin_any_server_n()
    test_cell1_slot_is_server2_for_manifest()
    test_node_title_for_slot()
    test_device_on_node_default_server1_stays_on_cell()
    test_node_online_shown_is_db_only()
    test_assign_online_unique_partition()
    print("ok")
