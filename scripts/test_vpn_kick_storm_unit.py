"""Invariants: unpaid leftover must not pin wdtt/API with per-peer wg set.

Incident 2026-08-28: after global test-off, every unpaid keepalive called
kick_if_subscription_denied → sync_unpaid_deny_net → kick_wg_peer_on_queen
for ALL unpaid identities, plus a 10s sweeper over last_connected<20min.
That is a kick storm. These tests fail if that pattern returns.

Run: python scripts/test_vpn_kick_storm_unit.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KICK = ROOT / "app" / "services" / "vpn_kick.py"
VPN = ROOT / "app" / "services" / "vpn_service.py"
DB = ROOT / "app" / "database.py"


def _module(path: Path) -> tuple[str, ast.AST]:
    src = path.read_text(encoding="utf-8")
    return src, ast.parse(src)


def _fn(tree: ast.AST, src: str, name: str) -> str:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            chunk = ast.get_source_segment(src, node)
            if not chunk:
                raise AssertionError(f"empty source for {name}")
            return chunk
    raise AssertionError(f"missing function {name}")


def test_sync_unpaid_is_iptables_only():
    src, tree = _module(KICK)
    body = _fn(tree, src, "sync_unpaid_deny_net")
    assert "sync_queen_deny_ips" in body, "deny must still apply iptables"
    assert "kick_wg_peer_on_queen" not in body, (
        "sync_unpaid_deny_net must not per-peer wg kick "
        "(test-off leftover storm 2026-08-28)"
    )
    assert "remove_wg_peers_batch_on_queen" not in body


def test_unpaid_online_does_not_nsenter():
    src, tree = _module(KICK)
    body = _fn(tree, src, "kick_if_subscription_denied")
    for banned in (
        "kick_device_peers",
        "sync_unpaid_deny_net",
        "kick_wg_peer_on_queen",
        "sync_cell_manifest_by_id",
    ):
        assert banned not in body, f"kick_if_subscription_denied must not call {banned}"


def test_sweeper_not_last20min_per_peer():
    src, tree = _module(KICK)
    body = _fn(tree, src, "kick_connected_without_subscription")
    assert "drop_unpaid_queen_peers_batch" in body
    assert "disable_queen_deny" not in body, "fail-open must not undo SILENT_DENY every API start"
    assert "timedelta(minutes=20)" not in body, (
        "do not sweep last_connected<20min with per-peer kick"
    )
    # watched-only may still kick_device_peers; mass leftover must be batch
    assert "drop_unpaid_queen_peers_batch" in body


def test_bind_extra_does_not_start_watch():
    src, tree = _module(KICK)
    body = _fn(tree, src, "_bind_extra_pub")
    assert "watch_device_revoke" not in body, (
        "binding an extra must not start 25min sweeper watch "
        "(that re-kicked leftover devices every 10s)"
    )


def test_online_hot_path_uses_access_cache():
    src, tree = _module(VPN)
    body = _fn(tree, src, "set_device_online")
    assert "users_with_vpn_access_ids_cached" in body
    assert "user_has_active_subscription" not in body, (
        "ensure_trial on every wdtt keepalive was part of the CPU pile-up"
    )


def test_db_pool_not_thousands():
    src = DB.read_text(encoding="utf-8")
    size = int(re.search(r"pool_size\s*=\s*(\d+)", src).group(1))
    overflow = int(re.search(r"max_overflow\s*=\s*(\d+)", src).group(1))
    assert size <= 40, f"pool_size={size} — Postgres max_connections=100, do not raise to thousands"
    assert overflow <= 20, f"max_overflow={overflow}"


def test_drop_unpaid_is_batch():
    src, tree = _module(KICK)
    body = _fn(tree, src, "drop_unpaid_queen_peers_batch")
    assert "remove_wg_peers_batch_on_queen" in body
    assert "kick_wg_peer_on_queen" not in body


if __name__ == "__main__":
    test_sync_unpaid_is_iptables_only()
    test_unpaid_online_does_not_nsenter()
    test_sweeper_not_last20min_per_peer()
    test_bind_extra_does_not_start_watch()
    test_online_hot_path_uses_access_cache()
    test_db_pool_not_thousands()
    test_drop_unpaid_is_batch()
    print("ok")
