"""Unit tests: GETCONF extra picking on cells vs queen (no DB)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from app.services.vpn_kick_select import (  # noqa: E402
    LivePeer,
    count_keys_absent,
    device_looks_live,
    merge_known_device_pubs,
    page_round_robin,
    parse_wg_show_dump,
    pick_getconf_extras,
    select_gc_extra_pubs,
    select_owned_getconf_extras,
    select_extra_by_last_connected,
    select_resurrected_extras,
    should_keep_vpn_dataplane,
    should_mark_unpaid_offline,
    snapshot_appeared,
)


def _p(pub: str, ip: str, age: float) -> LivePeer:
    return LivePeer(pub=pub, ip=ip, handshake_age=age)


def _k(tag: str) -> str:
    return (tag + ("a" * 43))[:43] + "="


def test_parse_wg_show_dump():
    allowed = (
        "aaaabbbbccccddddeeeeffffgggghhhhiiiijjjj= 10.66.0.25/32\n"
        "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz= 10.66.0.23/32\n"
    )
    now = 1_000_000.0
    hs = (
        f"aaaabbbbccccddddeeeeffffgggghhhhiiiijjjj= {int(now - 5)}\n"
        f"zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz= {int(now - 74)}\n"
    )
    peers = parse_wg_show_dump(allowed, hs, now=now)
    by_ip = {p.ip: int(p.handshake_age or -1) for p in peers}
    assert by_ip["10.66.0.25"] == 5
    assert by_ip["10.66.0.23"] == 74


def test_cell_never_guesses_extras():
    """Must not kick newest leftover — that was other users on the cell."""
    extras = [
        _p("newestpubkeyaaaaaaaaaaaaaaaaaaaaaaaaaaa=", "10.66.0.19", 5),
        _p("oldpubkeybbbbbbbbbbbbbbbbbbbbbbbbbbbbb=", "10.66.0.18", 27),
        _p("leftovercccccccccccccccccccccccccccccc=", "10.66.0.23", 74),
    ]
    now = 1_000_000.0
    last = datetime.fromtimestamp(now - 74, tz=timezone.utc)
    picked = pick_getconf_extras(
        extras,
        on_queen=False,
        device_is_live=True,
        last_connected=last,
        now=now,
    )
    assert picked == []


def test_cell_skips_extras_for_idle_old_device():
    extras = [_p("newestpubkeyaaaaaaaaaaaaaaaaaaaaaaaaaaa=", "10.66.0.19", 5)]
    picked = pick_getconf_extras(
        extras,
        on_queen=False,
        device_is_live=False,
        last_connected=None,
    )
    assert picked == []


def test_queen_does_not_pick_newest_of_many():
    extras = [
        _p("newestpubkeyaaaaaaaaaaaaaaaaaaaaaaaaaaa=", "10.66.7.53", 12),
        _p("other1bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb=", "10.66.1.89", 20),
        _p("other2cccccccccccccccccccccccccccccccc=", "10.66.3.102", 30),
    ]
    picked = pick_getconf_extras(
        extras,
        on_queen=True,
        device_is_live=True,
        last_connected=None,
    )
    assert picked == []


def test_queen_solo_extras_all_kicked():
    extras = [
        _p("a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1=", "10.66.0.1", 3),
        _p("b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2b2=", "10.66.0.2", 8),
    ]
    picked = pick_getconf_extras(
        extras,
        on_queen=True,
        device_is_live=True,
        last_connected=None,
    )
    assert picked == []


def test_device_looks_live_watch_overrides_stale():
    dev = SimpleNamespace(is_connected=False, last_connected=None)
    assert device_looks_live(dev, watch=False) is False
    assert device_looks_live(dev, watch=True) is True


def test_device_looks_live_recent_last_connected():
    dev = SimpleNamespace(
        is_connected=False,
        last_connected=datetime.utcnow() - timedelta(minutes=5),
    )
    assert device_looks_live(dev) is True
    old = SimpleNamespace(
        is_connected=False,
        last_connected=datetime.utcnow() - timedelta(hours=3),
    )
    assert device_looks_live(old) is False


def test_gc_keeps_device_key_even_if_never_hs():
    known = {"devicekeyaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="}
    live = [
        LivePeer("devicekeyaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=", "10.66.0.2", None),
        LivePeer("deadextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=", "10.66.0.9", None),
        LivePeer("liveextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=", "10.66.0.3", 30.0),
        LivePeer("oldextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=", "10.66.0.8", 7 * 3600.0),
    ]
    got = set(select_gc_extra_pubs(live, known))
    assert "devicekeyaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=" not in got
    assert "liveextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=" not in got
    assert "deadextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=" in got
    assert "oldextraaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa=" in got


def test_gc_drops_getconf_live_key_with_no_handshake():
    """wg_live_public_key leftovers must not protect never-hs extras (hive 121 ghosts)."""
    identity = _k("devicekey")
    leftover_live = _k("oldlivekey")
    known = {identity}
    live = [
        LivePeer(identity, "10.66.0.2", 20.0),
        LivePeer(leftover_live, "10.66.0.9", None),
    ]
    got = set(select_gc_extra_pubs(live, known))
    assert identity not in got
    assert leftover_live in got


def test_keep_dataplane_for_test_and_paid():
    assert should_keep_vpn_dataplane(
        is_admin=False, in_test_mode=True, has_live_test_plan=False, has_active_subscription=False,
    )
    assert should_keep_vpn_dataplane(
        is_admin=False, in_test_mode=False, has_live_test_plan=True, has_active_subscription=False,
    )
    assert should_keep_vpn_dataplane(
        is_admin=False, in_test_mode=False, has_live_test_plan=False, has_active_subscription=True,
    )
    assert should_keep_vpn_dataplane(
        is_admin=True, in_test_mode=False, has_live_test_plan=False, has_active_subscription=False,
    )
    assert not should_keep_vpn_dataplane(
        is_admin=False, in_test_mode=False, has_live_test_plan=False, has_active_subscription=False,
    )


def test_owned_extras_same_ip():
    known = {_k("devicekey")}
    live = [
        _p(_k("devicekey"), "10.66.0.25", 4),
        _p(_k("getconfextra"), "10.66.0.25", 2),
        _p(_k("stranger"), "10.66.0.19", 1),
    ]
    got = {p.pub for p in select_owned_getconf_extras(
        live, known_pubs=known, device_ip="10.66.0.25/32",
    )}
    assert _k("getconfextra") in got
    assert _k("stranger") not in got
    assert _k("devicekey") not in got


def test_owned_extras_unique_appeared():
    known = {_k("devicekey")}
    live = [
        _p(_k("oldpaying"), "10.66.0.19", 8),
        _p(_k("brandnew"), "10.66.0.44", 1),
    ]
    got = select_owned_getconf_extras(
        live,
        known_pubs=known,
        device_ip="10.66.0.25/32",
        appeared_pubs={_k("brandnew")},
        unique_watch_on_node=True,
    )
    assert [p.pub for p in got] == [_k("brandnew")]


def test_owned_extras_solo_unknown_on_quiet_node():
    """Тихая сота: не забирать единственный extra без совпадения IP."""
    known = {_k("devicekey")}
    live = [
        _p(_k("devicekey"), "10.66.0.25", 4),
        _p(_k("onlyextra"), "10.66.0.44", 2),
    ]
    got = select_owned_getconf_extras(
        live, known_pubs=known, device_ip="10.66.0.99/32", unique_watch_on_node=True,
    )
    assert got == []
    busy = live + [_p(_k("otherlive"), "10.66.0.19", 3)]
    got2 = select_owned_getconf_extras(
        busy, known_pubs=known, device_ip="10.66.0.99/32", unique_watch_on_node=True,
    )
    assert got2 == []


def test_sweeper_style_no_guess_on_quiet_cell():
    """Фоновый kick без bind_new: только extra с тем же IP, не чужой на Соте 2."""
    known = {_k("unpaid")}
    live = [
        _p(_k("unpaid"), "10.66.2.150", 80),
        _p(_k("payingnew"), "10.66.66.35", 2),
    ]
    got = select_owned_getconf_extras(
        live,
        known_pubs=known,
        device_ip="10.66.2.150/32",
        appeared_pubs={_k("payingnew")},
        unique_watch_on_node=False,
    )
    assert got == []


def test_owned_extras_two_appeared_not_guessed():
    known = set()
    live = [
        _p(_k("newest"), "10.66.0.19", 5),
        _p(_k("other1"), "10.66.0.18", 6),
        _p(_k("other2"), "10.66.0.17", 7),
    ]
    got = select_owned_getconf_extras(
        live,
        known_pubs=known,
        device_ip="10.66.0.25/32",
        appeared_pubs={p.pub for p in live},
        unique_watch_on_node=True,
    )
    assert got == []


def test_owned_extras_ip_not_substring():
    known = set()
    live = [_p(_k("other20"), "10.66.66.20", 3)]
    got = select_owned_getconf_extras(
        live, known_pubs=known, device_ip="10.66.66.2/32",
    )
    assert got == []


def test_last_connected_unique_leftover():
    known = {_k("device")}
    now = 1_000_000.0
    last = datetime.fromtimestamp(now - 40, tz=timezone.utc)
    live = [
        _p(_k("paying"), "10.66.0.19", 5),
        _p(_k("leftover"), "10.66.0.44", 40),
        _p(_k("other"), "10.66.0.18", 80),
    ]
    got = select_extra_by_last_connected(live, last, known, now=now)
    assert [p.pub for p in got] == [_k("leftover")]
    two = live + [_p(_k("also40"), "10.66.0.33", 41)]
    assert select_extra_by_last_connected(two, last, known, now=now) == []


def test_resurrected_unique_cache_extra():
    known = {_k("device")}
    leftover = _k("leftover")
    live = [
        _p(_k("paying"), "10.66.0.19", 4),
        _p(leftover, "10.66.0.44", 1),
    ]
    prev = {_k("paying"): 6.0, leftover: 55.0}
    got = select_resurrected_extras(live, prev, known)
    assert [p.pub for p in got] == [leftover]
    prev2 = {_k("paying"): 6.0, leftover: 2.0}
    assert select_resurrected_extras(live, prev2, known) == []


def test_snapshot_appeared():
    a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa="
    b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb="
    c = "ccccccccccccccccccccccccccccccccccccccc="
    first, snap = snapshot_appeared(None, {a, b})
    assert first == set()
    appeared, snap2 = snapshot_appeared(snap, {a, b, c})
    assert appeared == {c}
    none, _ = snapshot_appeared(snap2, {a, b})
    assert none == set()


def test_safe_deny_ip_and_wdtt_identities():
    from app.services.vpn_deny_net import collect_ips, identities_from_wdtt_db, is_safe_deny_ip

    assert is_safe_deny_ip("10.66.0.25")
    assert is_safe_deny_ip("10.66.2.104/32")
    assert not is_safe_deny_ip("10.66.66.1")
    assert not is_safe_deny_ip("10.66.66.2")
    assert not is_safe_deny_ip("8.8.8.8")
    assert not is_safe_deny_ip("")
    assert collect_ips("10.66.0.25/32", "10.66.66.1", "10.66.66.2", "nope") == {"10.66.0.25"}
    blob = {
        "devices": {
            "boot:abc": {"ip": "10.66.0.2", "pub_key": "x"},
            "dev-1": {"ip": "10.66.0.25/32", "pub_key": "pub1"},
            "dev-2": {"ip": "8.8.8.8", "pub_key": "pub2"},
        }
    }
    got = identities_from_wdtt_db(blob, ["boot:abc", "dev-1", "dev-2", "missing"])
    assert "boot:abc" not in got
    assert got["dev-1"]["ip"] == "10.66.0.25"
    assert "ip" not in got.get("dev-2", {})
    from app.services.vpn_deny_net import unpaid_ips_from_wdtt_only

    mixed = {
        "dev-1": {"ip": "10.66.0.25"},
        "dev-2": {"ip": "10.66.66.2"},
        "dev-3": {"ip": "10.66.5.144"},
    }
    assert unpaid_ips_from_wdtt_only(mixed) == {"10.66.0.25", "10.66.5.144"}


def test_deny_ids_tmp_paths_are_unique():
    from app.services.vpn_deny_net import deny_ids_tmp_path, _iptables_sync_script

    a = deny_ids_tmp_path()
    b = deny_ids_tmp_path()
    assert a != b
    assert a.startswith("/tmp/silent-deny-ids-")
    script = _iptables_sync_script({"10.66.0.25"})
    assert " && " in script
    assert script.count("iptables -A") >= 2


def test_unpaid_page_advances_tail():
    keys = [f"k{i}" for i in range(5)]
    page1, cur = page_round_robin(keys, cursor=0, limit=2)
    page2, cur = page_round_robin(keys, cursor=cur, limit=2)
    page3, _ = page_round_robin(keys, cursor=cur, limit=2)
    assert page1 == ["k0", "k1"]
    assert page2 == ["k2", "k3"]
    assert "k4" in page3


def test_removed_count_and_offline_only_matching_pubs():
    key = "aaaabbbbccccddddeeeeffffgggghhhhiiiijjjj="
    other = "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz="
    assert count_keys_absent([key, other], {other}) == 1
    assert should_mark_unpaid_offline({key}, {key})
    assert not should_mark_unpaid_offline({other}, {key})
    assert merge_known_device_pubs([key, ""], [other, None]) == {key, other}


if __name__ == "__main__":
    test_parse_wg_show_dump()
    test_cell_never_guesses_extras()
    test_cell_skips_extras_for_idle_old_device()
    test_queen_does_not_pick_newest_of_many()
    test_queen_solo_extras_all_kicked()
    test_device_looks_live_watch_overrides_stale()
    test_device_looks_live_recent_last_connected()
    test_gc_keeps_device_key_even_if_never_hs()
    test_gc_drops_getconf_live_key_with_no_handshake()
    test_keep_dataplane_for_test_and_paid()
    test_owned_extras_same_ip()
    test_owned_extras_unique_appeared()
    test_owned_extras_two_appeared_not_guessed()
    test_owned_extras_solo_unknown_on_quiet_node()
    test_sweeper_style_no_guess_on_quiet_cell()
    test_owned_extras_ip_not_substring()
    test_last_connected_unique_leftover()
    test_resurrected_unique_cache_extra()
    test_snapshot_appeared()
    test_safe_deny_ip_and_wdtt_identities()
    test_deny_ids_tmp_paths_are_unique()
    test_unpaid_page_advances_tail()
    test_removed_count_and_offline_only_matching_pubs()
    print("ok")
