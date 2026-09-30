"""Admin loading regression: first page is bounded and dashboard fast path skips live refresh."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api import admin as api  # noqa: E402
from app.services import hive_service, peak_online, subscription_service, wg_peer_gc  # noqa: E402


async def test_paged_users_search_and_sort() -> None:
    now = datetime(2026, 9, 30)
    rows = [
        {"id": "admin", "email": "admin@example.test", "display_id": "00", "is_admin": True,
         "is_online": False, "is_verified": True, "created_at": now - timedelta(days=9),
         "subscription": {"active": True, "plan": "unlimited"}},
        {"id": "a", "email": "alpha@example.test", "display_id": "01", "is_admin": False,
         "is_online": False, "is_verified": True, "created_at": now - timedelta(days=3),
         "subscription": {"active": False, "plan": None}},
        {"id": "b", "email": "beta@example.test", "display_id": "02", "is_admin": False,
         "is_online": True, "is_verified": True, "created_at": now - timedelta(days=2),
         "subscription": {"active": True, "plan": "monthly"}},
        {"id": "c", "email": "charlie@example.test", "display_id": "03", "is_admin": False,
         "is_online": False, "is_verified": False, "created_at": now - timedelta(days=1),
         "subscription": {"active": False, "plan": None}},
    ]
    for row in rows:
        row["in_test_mode"] = False
    original = api.list_users

    async def fake_list_users(**kwargs):
        return rows

    api.list_users = fake_list_users
    try:
        page1 = await api.list_users_paged(q="", page=1, page_size=2, sort="online", _=True, db=None)
        assert [r["id"] for r in page1["items"]] == ["admin", "b"]
        assert page1["total"] == 4 and page1["matched"] == 4
        page2 = await api.list_users_paged(q="", page=2, page_size=2, sort="online", _=True, db=None)
        assert [r["id"] for r in page2["items"]] == ["c", "a"]
        found = await api.list_users_paged(q="03", page=1, page_size=2, sort="registered_new", _=True, db=None)
        assert found["matched"] == 1 and found["items"][0]["id"] == "c"
        subscription = await api.list_users_paged(q="", page=1, page_size=4, sort="subscription", _=True, db=None)
        assert [r["id"] for r in subscription["items"]] == ["admin", "b", "c", "a"]
    finally:
        api.list_users = original


async def test_fast_dashboard_skips_live_online() -> None:
    original_users = api._dashboard_users_block
    original_nodes = api.list_dashboard_resource_nodes
    original_system = api.dashboard_system_for_node
    modes = []

    async def fake_users(db, *, soft_online=False, fast=False):
        modes.append((soft_online, fast))
        return {"total": 4, "connected_devices": None}

    async def fake_nodes(db):
        return [{"id": "queen", "is_queen": True}]

    async def fake_system(db, node):
        return {"node_id": node}

    api._dashboard_users_block = fake_users
    api.list_dashboard_resource_nodes = fake_nodes
    api.dashboard_system_for_node = fake_system
    try:
        result = await api.get_stats(light=False, fast=True, node_id="queen", _=True, db=None)
        assert modes == [(False, True)]
        assert result["users"]["connected_devices"] is None
        assert result["system"]["node_id"] == "queen"
        assert "vk_users" not in result
    finally:
        api._dashboard_users_block = original_users
        api.list_dashboard_resource_nodes = original_nodes
        api.dashboard_system_for_node = original_system


async def test_fast_users_block_does_not_refresh_hive() -> None:
    original_count = api._count_users_with_vpn_access
    original_breakdown = subscription_service.dashboard_subscription_breakdown
    original_cached = hive_service.cached_vpn_online_shown
    original_online = hive_service.vpn_online_shown_total
    original_peak = peak_online.get_peak_online

    async def count(db):
        return 4, 2

    async def breakdown(db):
        return {"total": 2, "paid": 2, "granted": 0, "referral": 0, "trial": 0}

    async def no_refresh(db, *, soft=False):
        raise AssertionError("fast dashboard must not refresh hive")

    async def peak(db):
        return 3, None

    api._count_users_with_vpn_access = count
    subscription_service.dashboard_subscription_breakdown = breakdown
    hive_service.cached_vpn_online_shown = lambda: None
    hive_service.vpn_online_shown_total = no_refresh
    peak_online.get_peak_online = peak
    try:
        result = await api._dashboard_users_block(None, fast=True)
        assert result["total"] == 4
        assert result["connected_devices"] is None
        assert result["peak_online_devices"] == 3
    finally:
        api._count_users_with_vpn_access = original_count
        subscription_service.dashboard_subscription_breakdown = original_breakdown
        hive_service.cached_vpn_online_shown = original_cached
        hive_service.vpn_online_shown_total = original_online
        peak_online.get_peak_online = original_peak


async def test_compact_dashboard_keeps_grouped_hashes_and_legacy_contract() -> None:
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, email="one@example.test", created_at=datetime(2026, 9, 1),
                           last_seen_at=None)
    slot = SimpleNamespace(user_id=user_id, slot_index=0, fail_count=0, updated_at=None,
                           hash_value="sample-hash", is_active=True, last_error_code=0,
                           last_checked=None)

    class Rows:
        def __init__(self, items):
            self.items = items

        def scalars(self):
            return self

        def all(self):
            return self.items

    class Db:
        def __init__(self):
            self.calls = 0

        async def execute(self, query):
            self.calls += 1
            return Rows(([user], [], [], [slot])[self.calls - 1])

    original_users = api._dashboard_users_block
    original_nodes = api.list_dashboard_resource_nodes
    original_system = api.dashboard_system_for_node
    original_live = wg_peer_gc.queen_live_pubs_3m
    original_cached = hive_service.cached_dashboard_live_pubs

    async def fake_users(db, **kwargs):
        return {"total": 1, "connected_devices": 0}

    async def fake_nodes(db):
        return [{"id": "queen", "is_queen": True}]

    async def fake_system(db, node):
        return {"node_id": node}

    api._dashboard_users_block = fake_users
    api.list_dashboard_resource_nodes = fake_nodes
    api.dashboard_system_for_node = fake_system
    wg_peer_gc.queen_live_pubs_3m = lambda: set()
    hive_service.cached_dashboard_live_pubs = lambda: set()
    try:
        compact = await api.get_stats(light=False, fast=False, compact=True,
                                      node_id="queen", _=True, db=Db())
        legacy = await api.get_stats(light=False, fast=False, compact=False,
                                     node_id="queen", _=True, db=Db())
        assert compact["vk_hashes"] == []
        assert compact["vk_users"][0]["hashes"][0]["hash"] == "sample-hash"
        assert compact["vk_hash_summary"]["total_active"] == 1
        assert len(legacy["vk_hashes"]) == 1
    finally:
        api._dashboard_users_block = original_users
        api.list_dashboard_resource_nodes = original_nodes
        api.dashboard_system_for_node = original_system
        wg_peer_gc.queen_live_pubs_3m = original_live
        hive_service.cached_dashboard_live_pubs = original_cached


if __name__ == "__main__":
    asyncio.run(test_paged_users_search_and_sort())
    asyncio.run(test_fast_dashboard_skips_live_online())
    asyncio.run(test_fast_users_block_does_not_refresh_hive())
    asyncio.run(test_compact_dashboard_keeps_grouped_hashes_and_legacy_contract())
    print("ok: bounded users page and fast dashboard")
