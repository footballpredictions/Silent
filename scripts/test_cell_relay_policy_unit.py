"""Unit tests: dry-run релей вход→Сервер 4 (без iptables и wdtt)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from ai.availability_model import (  # noqa: E402
    CHANNEL_PING,
    CHANNEL_WDTT_UDP,
    ERR_TIMEOUT,
    NodeResult,
    TARGET_CELL,
    TARGET_QUEEN,
    TargetSnapshot,
    VantageAggregate,
)
from ai.cell_relay_policy import ACTION_DIRECT, ACTION_HOLD, ACTION_RELAY, build_relay_plan  # noqa: E402


def _agg(channel: str, *, ok: int = 0, failed: int = 0) -> VantageAggregate:
    nodes = [NodeResult(node=f"ru{i}.node", ok=True, latency_ms=40.0) for i in range(ok)]
    nodes += [
        NodeResult(node=f"ru{ok + i}.node", ok=False, error_kind=ERR_TIMEOUT, detail="timeout")
        for i in range(failed)
    ]
    return VantageAggregate(channel=channel, nodes=nodes)


def _snap(name: str, role: str, *, ai_exit: bool = False, udp_ok: bool | None = None, ping_ok: bool | None = None):
    ru = {}
    if udp_ok is not None:
        ru[CHANNEL_WDTT_UDP] = _agg(CHANNEL_WDTT_UDP, ok=1 if udp_ok else 0, failed=0 if udp_ok else 2)
    if ping_ok is not None:
        ru[CHANNEL_PING] = _agg(CHANNEL_PING, ok=1 if ping_ok else 0, failed=0 if ping_ok else 2)
    return TargetSnapshot(name=name, host=f"{name}.example", role=role, ai_exit=ai_exit, ru=ru)


def test_reachable_ai_cell_stays_direct():
    plan = build_relay_plan(
        [
            _snap("Улей", TARGET_QUEEN, udp_ok=True),
            _snap("Сота 1", TARGET_CELL, udp_ok=True),
            _snap("сота3", TARGET_CELL, ai_exit=True, udp_ok=True),
        ]
    )
    hop = next(h for h in plan["hops"] if h["ai_exit"])
    assert hop["action"] == ACTION_DIRECT
    assert plan["executed"] is False


def test_blocked_server4_relays_via_live_cell():
    plan = build_relay_plan(
        [
            _snap("Улей", TARGET_QUEEN, udp_ok=True),
            _snap("Сота 1", TARGET_CELL, udp_ok=True),
            _snap("сота3", TARGET_CELL, ai_exit=True, udp_ok=False, ping_ok=False),
        ]
    )
    hop = next(h for h in plan["hops"] if h["ai_exit"])
    assert hop["action"] == ACTION_RELAY
    assert hop["entry"] == "Сота 1"
    assert hop["exit"] == "сота3"
    assert plan["executed"] is False
    assert "iptables" not in plan["explain"].lower() or "не" in plan["explain"].lower()


def test_unknown_udp_does_not_invent_relay():
    """Нет пробы WDTT — fail-safe прямой ход, иначе сменим выход ИИ на чужой."""
    plan = build_relay_plan(
        [
            _snap("Сота 1", TARGET_CELL, udp_ok=True),
            _snap("сота3", TARGET_CELL, ai_exit=True),
        ]
    )
    hop = next(h for h in plan["hops"] if h["ai_exit"])
    assert hop["action"] == ACTION_DIRECT


def test_all_blocked_holds():
    plan = build_relay_plan(
        [
            _snap("Улей", TARGET_QUEEN, udp_ok=False, ping_ok=False),
            _snap("Сота 1", TARGET_CELL, udp_ok=False, ping_ok=False),
            _snap("сота3", TARGET_CELL, ai_exit=True, udp_ok=False, ping_ok=False),
        ]
    )
    hop = next(h for h in plan["hops"] if h["ai_exit"])
    assert hop["action"] == ACTION_HOLD
    assert hop["entry"] is None


def test_prefers_ordinary_cell_over_queen():
    plan = build_relay_plan(
        [
            _snap("Улей", TARGET_QUEEN, udp_ok=True),
            _snap("Сота 1", TARGET_CELL, udp_ok=True),
            _snap("сота3", TARGET_CELL, ai_exit=True, udp_ok=False, ping_ok=False),
        ]
    )
    hop = next(h for h in plan["hops"] if h["ai_exit"])
    assert hop["entry"] == "Сота 1"


def test_does_not_use_ai_exit_as_entry_for_another_cell():
    plan = build_relay_plan(
        [
            _snap("Сота 1", TARGET_CELL, udp_ok=False, ping_ok=False),
            _snap("сота3", TARGET_CELL, ai_exit=True, udp_ok=True),
        ]
    )
    hop = next(h for h in plan["hops"] if h["name"] == "Сота 1")
    assert hop["action"] == ACTION_HOLD or hop.get("entry") != "сота3"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ok ({len(tests)} tests)")
