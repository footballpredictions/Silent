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
    device_shown_online,
    is_manual_server_pin,
    merge_live_wg_pubs,
    node_online_shown,
    node_title_for_cell,
    node_title_for_slot,
    parse_manual_slot,
    pick_dashboard_shown_online,
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


def test_node_online_shown_never_hides_people_behind_zero_wg():
    """Нагрузка на соте + is_connected, а агент отдал wg_live=0 — людей не прячем."""
    assert node_online_shown(is_queen=False, db_online=4, wg_live=0) == 4
    assert node_online_shown(is_queen=True, db_online=3, wg_live=0) == 3
    assert node_online_shown(is_queen=True, db_online=71, wg_live=None) == 71


def test_node_online_shown_takes_the_higher_of_db_and_wg():
    """Сота: keepalive ещё не дошёл (db=0), но handshake живые — показать WG."""
    assert node_online_shown(is_queen=True, db_online=79, wg_live=91) == 91
    assert node_online_shown(is_queen=False, db_online=0, wg_live=8) == 8
    assert node_online_shown(is_queen=False, db_online=2, wg_live=12) == 12
    assert node_online_shown(is_queen=True, db_online=3, wg_live=6) == 6


def test_dashboard_online_is_sum_of_hive_cards():
    """Шапка = сумма карточек: люди из БД и с нод, нулевой WG соту не обнуляет."""
    hive_cards = [
        node_online_shown(is_queen=True, db_online=3, wg_live=6),
        node_online_shown(is_queen=False, db_online=12, wg_live=0),
        node_online_shown(is_queen=False, db_online=0, wg_live=8),
        node_online_shown(is_queen=False, db_online=0, wg_live=0),
    ]
    assert hive_cards == [6, 12, 8, 0]
    assert sum(hive_cards) == 26


def test_light_poll_uses_shared_wg_not_db():
    """2 uvicorn worker: light-полл не прыгает на is_connected из БД (79 vs 102)."""
    db_total = 79
    wg_live = 102
    assert pick_dashboard_shown_online(ram=wg_live, shared=None, stale_ram=None, soft=True) == wg_live
    assert pick_dashboard_shown_online(ram=None, shared=wg_live, stale_ram=None, soft=True) == wg_live
    assert pick_dashboard_shown_online(ram=None, shared=None, stale_ram=wg_live, soft=True) == wg_live
    assert pick_dashboard_shown_online(ram=None, shared=None, stale_ram=None, soft=True) is None
    assert pick_dashboard_shown_online(ram=None, shared=None, stale_ram=None, soft=True) != db_total
    assert pick_dashboard_shown_online(ram=None, shared=None, stale_ram=wg_live, soft=False) is None

    hive = (ROOT / "app" / "services" / "hive_service.py").read_text(encoding="utf-8")
    start = hive.index("async def vpn_online_shown_total")
    end = hive.index("\nasync def ", start + 10)
    fn = hive[start:end]
    assert "pick_dashboard_shown_online" in fn
    assert "hive:vpn_online_shown" in hive
    assert fn.index("refresh_online_shown_cache") < fn.index("connected_devices_by_cell")


def test_manual_server_select_has_no_online_cap():
    """Ручной Сервер 2/3 не смотрит max_online — лимит в карточке Улья не режет connect."""
    hive = (ROOT / "app" / "services" / "hive_service.py").read_text(encoding="utf-8")
    vpn = (ROOT / "app" / "services" / "vpn_service.py").read_text(encoding="utf-8")
    start = hive.index("async def apply_manual_server_cell")
    end = hive.index("\nasync def ", start + 10)
    apply_fn = hive[start:end]
    assert "max_online" not in apply_fn
    assert "max_clients" not in apply_fn
    start = hive.index("async def resolve_manual_server_cell")
    end = hive.index("\nasync def ", start + 10)
    resolve_fn = hive[start:end]
    assert "max_online" not in resolve_fn
    start = vpn.index("async def set_device_preferred_server")
    end = vpn.index("\nasync def ", start + 10)
    set_fn = vpn[start:end]
    assert "max_online" not in set_fn


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


def test_dashboard_online_row_keeps_cell_label():
    """Сортировка «Онлайн» на дашборде не должна подписывать соту как Улей."""
    queen = SimpleNamespace(is_queen=True, name="Улей")
    cell = SimpleNamespace(is_queen=False, name="Сота 1")
    unnamed = SimpleNamespace(is_queen=False, name="worker-alpha")
    assert node_title_for_cell(queen) == "Улей"
    assert node_title_for_cell(cell) == "Сота 1"
    assert node_title_for_cell(unnamed) == "worker-alpha"
    assert node_title_for_cell(None) == "Улей"


def test_vk_hash_list_online_is_67_not_9_db_flag():
    """Карточка VK-хешей зеленела по is_connected (9), шапка — по WG (67)."""
    live = {f"pub-live-{i}" for i in range(67)}
    devices = []
    for i in range(67):
        devices.append(
            SimpleNamespace(
                is_connected=(i < 9),
                wg_public_key=f"pub-id-{i}",
                wg_live_public_key=f"pub-live-{i}",
            )
        )
    db_only = sum(1 for d in devices if d.is_connected)
    shown = sum(1 for d in devices if device_shown_online(d, live))
    assert db_only == 9
    assert shown == 67
    assert not device_shown_online(
        SimpleNamespace(is_connected=False, wg_public_key="x", wg_live_public_key="y"),
        live,
    )


def test_merge_live_wg_pubs_skips_empty():
    assert merge_live_wg_pubs(None, [], {"a"}, [" b ", ""]) == {"a", "b"}


def test_get_stats_marks_vk_users_via_shown_online():
    admin = (ROOT / "app" / "api" / "admin.py").read_text(encoding="utf-8")
    assert "device_shown_online" in admin
    assert "users_online" in admin
    dash = (ROOT / "admin-ui" / "src" / "pages" / "DashboardPage.tsx").read_text(encoding="utf-8")
    assert "users_online" in dash
    assert "if (!prev) return prev" in dash


if __name__ == "__main__":
    test_slot_for_queen_and_named_cells()
    test_unnamed_worker_has_no_fixed_slot()
    test_manual_pin_any_server_n()
    test_cell1_slot_is_server2_for_manifest()
    test_node_title_for_slot()
    test_device_on_node_default_server1_stays_on_cell()
    test_node_online_shown_never_hides_people_behind_zero_wg()
    test_node_online_shown_takes_the_higher_of_db_and_wg()
    test_dashboard_online_is_sum_of_hive_cards()
    test_light_poll_uses_shared_wg_not_db()
    test_manual_server_select_has_no_online_cap()
    test_assign_online_unique_partition()
    test_dashboard_online_row_keeps_cell_label()
    test_vk_hash_list_online_is_67_not_9_db_flag()
    test_merge_live_wg_pubs_skips_empty()
    test_get_stats_marks_vk_users_via_shown_online()
    print("ok")
