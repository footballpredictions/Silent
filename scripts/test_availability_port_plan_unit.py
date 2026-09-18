"""Unit tests: dry-run план запасного порта API (без сети, БД и iptables)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from ai.availability_model import (  # noqa: E402
    CHANNEL_API_TCP,
    CHANNEL_API_TLS,
    CHANNEL_PING,
    ERR_TIMEOUT,
    NodeResult,
    ProbeResult,
    TARGET_QUEEN,
    TargetSnapshot,
    VantageAggregate,
)
from ai.availability_port_plan import (  # noqa: E402
    build_plan,
    needs_candidate_probe,
    next_all_failed_streak,
)
from ai.hive_api_port_policy import (  # noqa: E402
    ACTION_HOLD,
    ACTION_OPEN_CANDIDATE,
    KEEP_FOREVER,
)


def _agg(channel: str, *, ok: int = 0, failed: int = 0) -> VantageAggregate:
    nodes = [NodeResult(node=f"ru{i}.node", ok=True, latency_ms=40.0) for i in range(ok)]
    nodes += [
        NodeResult(node=f"ru{ok + i}.node", ok=False, error_kind=ERR_TIMEOUT, detail="timeout")
        for i in range(failed)
    ]
    return VantageAggregate(channel=channel, nodes=nodes)


def _queen(**kw) -> TargetSnapshot:
    snap = TargetSnapshot(
        name="Улей",
        host="89.125.188.100",
        role=TARGET_QUEEN,
        api_port=443,
        domain="89-125-188-100.nip.io",
        status="active",
    )
    snap.local[CHANNEL_API_TCP] = ProbeResult(channel=CHANNEL_API_TCP, ok=True, latency_ms=3.0)
    for k, v in kw.items():
        setattr(snap, k, v)
    return snap


def test_partial_rf_block_opens_alt_without_waiting_streak():
    """1/2 check-host — 443 для части РФ мёртв. Ждать 0/2 нельзя: окно так и не наберётся."""
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=1, failed=1)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=1, failed=1)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, ok=1, failed=1)
    plan, streak = build_plan(
        snap,
        previous_streak=4,
        candidate_reach={"2083": "open"},
        autoswitch_enabled=True,
        confirm_cycles=3,
    )
    assert streak == 0
    assert plan["action"] == ACTION_OPEN_CANDIDATE
    assert plan["port"] == 2083
    assert 443 in plan["keep_open"]
    assert plan["close_port"] is None


def test_all_ok_does_not_publish_alt():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=2)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, ok=2)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, ok=2)
    plan, _ = build_plan(
        snap,
        previous_streak=0,
        candidate_reach={"2083": "open"},
        autoswitch_enabled=True,
    )
    assert plan["action"] == ACTION_HOLD
    assert plan["port"] is None


def test_confirmed_block_opens_candidate_when_autoswitch():
    """Скрин админки: TCP 0/2, ping жив, автосмена включена — открываем 2083."""
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=2)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=2)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, failed=2)
    plan, streak = build_plan(
        snap,
        previous_streak=1,
        candidate_reach={"2083": "open", "2053": "timeout"},
        autoswitch_enabled=True,
        confirm_cycles=2,
    )
    assert streak == 2
    assert plan["action"] == ACTION_OPEN_CANDIDATE
    assert plan["port"] == 2083
    assert plan["reason"] == "rf_block"
    assert plan["executed"] is False, "публикацию делает исполнитель, не build_plan"


def test_dry_run_holds_when_autoswitch_off():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=2)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=2)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, failed=2)
    plan, _ = build_plan(
        snap,
        previous_streak=3,
        candidate_reach={"2083": "open"},
        autoswitch_enabled=False,
    )
    assert plan["action"] == ACTION_HOLD
    assert plan["suggested_port"] == 2083
    assert plan["reason"] == "dry_run"


def test_already_published_alt_does_not_open_next_candidate():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=2)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=2)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, failed=2)
    plan, _ = build_plan(
        snap,
        previous_streak=9,
        published_alt_ports=(2083,),
        candidate_reach={"2083": "open", "2053": "refused"},
        autoswitch_enabled=True,
    )
    assert plan["action"] == ACTION_HOLD
    assert plan["reason"] == "already_open"
    assert plan["suggested_port"] == 2083
    assert plan["port"] is None


def test_443_and_ssh_are_never_proposed_for_closing():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=2)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=2)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, failed=2)
    plan, _ = build_plan(snap, previous_streak=9, candidate_reach={"2083": "open"})
    assert plan["close_port"] is None
    for port in (443, 22, 80, 56000, 56001):
        assert port in KEEP_FOREVER
        assert port in plan["keep_open"] or port in KEEP_FOREVER


def test_local_443_down_is_our_breakage_not_block():
    snap = _queen()
    snap.local[CHANNEL_API_TCP] = ProbeResult(
        channel=CHANNEL_API_TCP, ok=False, error_kind="refused", detail="refused"
    )
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=2)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=2)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, failed=2)
    plan, _ = build_plan(snap, previous_streak=9, candidate_reach={"2083": "open"})
    assert plan["reason"] == "local_443_down"
    assert plan["suggested_port"] is None


def test_blackhole_does_not_suggest_new_port_on_same_ip():
    snap = _queen()
    snap.ru[CHANNEL_PING] = _agg(CHANNEL_PING, failed=2)
    snap.ru[CHANNEL_API_TCP] = _agg(CHANNEL_API_TCP, failed=2)
    snap.ru[CHANNEL_API_TLS] = _agg(CHANNEL_API_TLS, failed=2)
    plan, _ = build_plan(snap, previous_streak=9, candidate_reach={"2083": "open"})
    assert plan["reason"] == "ip_blackhole"
    assert plan["port"] is None


def test_candidate_probe_on_any_rf_tcp_fail():
    """1/2 тоже зовём кандидатов — иначе «не проверяли» и порт не сменить."""
    dead = {"tcp_ok": 0, "tcp_fail": 2, "tls_ok": 0, "tls_fail": 2}
    partial = {"tcp_ok": 1, "tcp_fail": 1, "tls_ok": 1, "tls_fail": 1}
    alive = {"tcp_ok": 2, "tcp_fail": 0, "tls_ok": 2, "tls_fail": 0}
    assert needs_candidate_probe(dead, 0)
    assert needs_candidate_probe(partial, 0)
    assert not needs_candidate_probe(alive, 9)


def test_streak_counts_only_fully_dead_windows():
    assert next_all_failed_streak(0, {"tcp_ok": 0, "tcp_fail": 2}) == 1
    assert next_all_failed_streak(5, {"tcp_ok": 0, "tcp_fail": 2}) == 6
    assert next_all_failed_streak(5, {"tcp_ok": 1, "tcp_fail": 1}) == 0
    assert next_all_failed_streak(5, {"tcp_ok": 0, "tcp_fail": 0}) == 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ok ({len(tests)} tests)")
