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
    device_looks_live,
    parse_wg_show_dump,
    pick_getconf_extras,
    select_gc_extra_pubs,
)


def _p(pub: str, ip: str, age: float) -> LivePeer:
    return LivePeer(pub=pub, ip=ip, handshake_age=age)


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


if __name__ == "__main__":
    test_parse_wg_show_dump()
    test_cell_never_guesses_extras()
    test_cell_skips_extras_for_idle_old_device()
    test_queen_does_not_pick_newest_of_many()
    test_queen_solo_extras_all_kicked()
    test_device_looks_live_watch_overrides_stale()
    test_device_looks_live_recent_last_connected()
    test_gc_keeps_device_key_even_if_never_hs()
    print("ok")
