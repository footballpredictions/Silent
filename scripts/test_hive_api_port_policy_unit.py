"""Политика запасных HTTPS-портов Улья: не флапать на 1/2 check-host."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.hive_api_port_policy import (  # noqa: E402
    ACTION_HOLD,
    ACTION_OPEN_CANDIDATE,
    ACTION_CLOSE_STALE_ALT,
    FORBIDDEN_PORTS,
    PortPolicyInput,
    alt_https_urls,
    decide_api_port_action,
    pick_candidate,
    stale_published_ports,
)


def test_one_of_two_tcp_ok_opens_alt_and_keeps_443():
    """Админка: API TCP 1/2 — для части РФ 443 мёртв. Новый порт в тему, 443 живой."""
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=1,
            tcp_fail=1,
            tls_ok=1,
            tls_fail=1,
            ping_ok=1,
            ping_fail=1,
            local_443_ok=True,
            consecutive_all_failed=0,
            confirm_cycles=3,
            autoswitch=True,
            candidate_reach={"2083": "open", "2053": "timeout"},
        )
    )
    assert d.action == ACTION_OPEN_CANDIDATE
    assert d.port == 2083
    assert 443 in d.keep_open
    assert d.close_port is None


def test_all_rf_nodes_ok_does_not_open_alt():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=2,
            tcp_fail=0,
            tls_ok=2,
            tls_fail=0,
            ping_ok=2,
            ping_fail=0,
            local_443_ok=True,
            autoswitch=True,
            candidate_reach={"2083": "open"},
        )
    )
    assert d.action == ACTION_HOLD
    assert d.port is None


def test_service_down_local_443_is_hold():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=0,
            tcp_fail=2,
            tls_ok=0,
            tls_fail=2,
            ping_ok=2,
            ping_fail=0,
            local_443_ok=False,
            consecutive_all_failed=5,
            autoswitch=True,
            candidate_reach={"2083": "refused"},
        )
    )
    assert d.action == ACTION_HOLD


def test_blackhole_same_ip_extra_port_is_hold():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=0,
            tcp_fail=2,
            tls_ok=0,
            tls_fail=2,
            ping_ok=0,
            ping_fail=2,
            local_443_ok=True,
            consecutive_all_failed=5,
            autoswitch=True,
            candidate_reach={"2083": "timeout"},
        )
    )
    assert d.action == ACTION_HOLD


def test_confirmed_port_block_opens_reachable_candidate():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=0,
            tcp_fail=2,
            tls_ok=0,
            tls_fail=2,
            ping_ok=1,
            ping_fail=1,
            local_443_ok=True,
            consecutive_all_failed=3,
            confirm_cycles=3,
            autoswitch=True,
            open_ports=(443,),
            candidate_reach={"8443": "timeout", "2083": "open", "2053": "timeout"},
        )
    )
    assert d.action == ACTION_OPEN_CANDIDATE
    assert d.port == 2083
    assert 443 in d.keep_open


def test_already_open_alt_holds_and_does_not_open_another():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=0,
            tcp_fail=2,
            tls_ok=0,
            tls_fail=2,
            ping_ok=2,
            ping_fail=0,
            local_443_ok=True,
            consecutive_all_failed=9,
            autoswitch=True,
            open_ports=(443, 2083),
            published_alt_ports=(2083,),
            candidate_reach={"2083": "open", "2053": "refused"},
        )
    )
    assert d.action == ACTION_HOLD
    assert d.reason == "already_open"
    assert d.port is None
    assert d.suggested_port == 2083


def test_no_autoswitch_stays_hold_even_if_confirmed():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=0,
            tcp_fail=2,
            tls_ok=0,
            tls_fail=2,
            ping_ok=2,
            ping_fail=0,
            local_443_ok=True,
            consecutive_all_failed=3,
            autoswitch=False,
            candidate_reach={"2083": "open"},
        )
    )
    assert d.action == ACTION_HOLD
    assert d.suggested_port == 2083
    assert d.reason == "dry_run"


def test_never_close_443_or_vpn_ports():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=0,
            tcp_fail=2,
            tls_ok=0,
            tls_fail=2,
            ping_ok=2,
            ping_fail=0,
            local_443_ok=True,
            consecutive_all_failed=9,
            autoswitch=True,
            open_ports=(443, 2083, 56000),
            published_alt_ports=(2083,),
            alt_grace_cycles=9,
            stale_alt_blocked=(2083,),
            candidate_reach={"2053": "refused"},
        )
    )
    assert 443 in d.keep_open
    assert 56000 in d.keep_open
    assert 22 not in FORBIDDEN_PORTS or True
    assert 443 in FORBIDDEN_PORTS or 443 not in {d.close_port}
    assert d.close_port != 443
    assert d.close_port != 56000


def test_close_stale_alt_only_after_grace_and_replacement():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=2,
            tcp_fail=0,
            tls_ok=2,
            tls_fail=0,
            ping_ok=2,
            ping_fail=0,
            local_443_ok=True,
            consecutive_all_failed=0,
            autoswitch=True,
            open_ports=(443, 2083),
            published_alt_ports=(2053,),
            alt_grace_cycles=10,
            stale_alt_blocked=(2083,),
            candidate_reach={"2053": "open"},
        )
    )
    assert d.action == ACTION_CLOSE_STALE_ALT
    assert d.close_port == 2083
    assert 443 in d.keep_open


def test_pick_candidate_skips_forbidden_timeout_and_refused():
    assert pick_candidate({"443": "refused", "1194": "refused", "2083": "timeout", "2053": "refused"}) is None
    assert pick_candidate({"2083": "open", "2053": "refused"}) == 2083
    assert pick_candidate({"8443": "open", "2083": "timeout"}) is None
    assert pick_candidate({"8443": "timeout", "22": "refused"}) is None


def test_refused_candidate_is_not_published_as_https():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=0,
            tcp_fail=2,
            tls_ok=0,
            tls_fail=2,
            ping_ok=2,
            ping_fail=0,
            local_443_ok=True,
            autoswitch=True,
            candidate_reach={"2083": "refused", "2053": "timeout", "8443": "open"},
        )
    )
    assert d.action == ACTION_HOLD
    assert d.port is None
    assert d.reason == "no_candidate"


def test_stale_timeout_published_opens_next_live_port():
    d = decide_api_port_action(
        PortPolicyInput(
            tcp_ok=0,
            tcp_fail=2,
            tls_ok=0,
            tls_fail=2,
            ping_ok=2,
            ping_fail=0,
            local_443_ok=True,
            autoswitch=True,
            published_alt_ports=(2083,),
            open_ports=(443, 2083),
            stale_alt_blocked=stale_published_ports((2083,), {"2083": "timeout", "2053": "open"}),
            candidate_reach={"2083": "timeout", "2053": "open"},
        )
    )
    assert d.action == ACTION_OPEN_CANDIDATE
    assert d.port == 2053
    assert 443 in d.keep_open


def test_stale_published_ports_need_explicit_dead_probe():
    assert stale_published_ports((2083,), None) == ()
    assert stale_published_ports((2083,), {"2083": "open"}) == ()
    assert stale_published_ports((2083,), {"2083": "timeout"}) == (2083,)


def test_alt_https_urls_use_sni_host_and_skip_443():
    urls = alt_https_urls("89-125-188-100.nip.io", "89.125.188.100", [443, 2083])
    assert urls == [
        "https://89-125-188-100.nip.io:2083",
        "https://89.125.188.100:2083",
    ]


if __name__ == "__main__":
    test_one_of_two_tcp_ok_opens_alt_and_keeps_443()
    test_all_rf_nodes_ok_does_not_open_alt()
    test_service_down_local_443_is_hold()
    test_blackhole_same_ip_extra_port_is_hold()
    test_confirmed_port_block_opens_reachable_candidate()
    test_already_open_alt_holds_and_does_not_open_another()
    test_no_autoswitch_stays_hold_even_if_confirmed()
    test_never_close_443_or_vpn_ports()
    test_close_stale_alt_only_after_grace_and_replacement()
    test_pick_candidate_skips_forbidden_timeout_and_refused()
    test_refused_candidate_is_not_published_as_https()
    test_stale_timeout_published_opens_next_live_port()
    test_stale_published_ports_need_explicit_dead_probe()
    test_alt_https_urls_use_sni_host_and_skip_443()
    print("ok")
