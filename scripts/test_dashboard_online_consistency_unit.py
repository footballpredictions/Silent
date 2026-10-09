"""Real dashboard count path: warm/cold workers must use the same shared snapshot."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.api import admin
from app.services import hive_service, peak_online, subscription_service
from app.services.hive_slots import pick_dashboard_shown_online


async def test_fast_worker_uses_shared_count(local: int | None):
    async def count(_): return 100, 90
    async def breakdown(_): return {"total": 90, "paid": 90, "granted": 0, "trial": 0}
    async def shared(): return 43
    async def peak(_): return 50, None
    async def refresh(): raise AssertionError("fast paint must not refresh nodes")
    with patch.object(admin, '_count_users_with_vpn_access', count), \
         patch.object(subscription_service, 'dashboard_subscription_breakdown', breakdown), \
         patch.object(hive_service, 'cached_vpn_online_shown', return_value=local), \
         patch.object(hive_service, '_redis_get_shown', shared), \
         patch.object(hive_service, 'refresh_online_shown_cache', refresh), \
         patch.object(peak_online, 'get_peak_online', peak):
        actual = (await admin._dashboard_users_block(None, fast=True))["connected_devices"]
        assert actual == 43, f"fast worker RAM={local}: online={actual}, shared snapshot=43"


def test_warm_poll_does_not_override_shared_snapshot():
    actual = pick_dashboard_shown_online(ram=12, shared=43, stale_ram=None, soft=True)
    assert actual == 43, f"light poll uses worker RAM={actual} instead of shared=43"


async def test_shared_zero_and_decrease_reach_all_modes():
    async def count(_): return 100, 90
    async def breakdown(_): return {"total": 90, "paid": 90, "granted": 0, "referral": 0, "trial": 0}
    async def peak(_): return 50, None
    async def record(_, n): return 50, None
    async def refresh(): raise AssertionError("cached modes must not refresh nodes")
    for shared_count in (43, 7, 0):
        async def shared(): return shared_count
        with patch.object(admin, '_count_users_with_vpn_access', count), \
             patch.object(subscription_service, 'dashboard_subscription_breakdown', breakdown), \
             patch.object(hive_service, 'cached_vpn_online_shown', return_value=99), \
             patch.object(hive_service, '_redis_get_shown', shared), \
             patch.object(hive_service, 'refresh_online_shown_cache', refresh), \
             patch.object(peak_online, 'get_peak_online', peak), \
             patch.object(peak_online, 'record_online_peak', record):
            for kwargs in ({'fast': True}, {'soft_online': True}, {}):
                actual = (await admin._dashboard_users_block(None, **kwargs))['connected_devices']
                assert actual == shared_count, f"{kwargs}: {actual} != shared {shared_count}"


async def test_redis_outage_has_bounded_ram_fallback():
    class HungRedis:
        async def get(self, _):
            await asyncio.sleep(10)
            raise AssertionError('must cancel hung Redis')
    started = time.monotonic()
    with patch.object(hive_service, '_get_shown_redis', return_value=HungRedis()), \
         patch.object(hive_service, 'cached_vpn_online_shown', return_value=12):
        actual = await hive_service.cached_vpn_online_shown_shared()
        assert actual == 12
    assert time.monotonic() - started < 1.5, 'Redis outage blocked fast paint'
    async def absent(): return None
    with patch.object(hive_service, '_redis_get_shown', absent), \
         patch.object(hive_service, 'cached_vpn_online_shown', return_value=None):
        assert await hive_service.cached_vpn_online_shown_shared() is None


if __name__ == '__main__':
    failures = 0
    for name, run in (
        ('fast warm worker', lambda: asyncio.run(test_fast_worker_uses_shared_count(12))),
        ('fast cold worker after deploy', lambda: asyncio.run(test_fast_worker_uses_shared_count(None))),
        ('light warm worker', test_warm_poll_does_not_override_shared_snapshot),
        ('all modes reflect zero and decreasing count', lambda: asyncio.run(test_shared_zero_and_decrease_reach_all_modes())),
        ('bounded Redis outage and cold-cache fallback', lambda: asyncio.run(test_redis_outage_has_bounded_ram_fallback())),
    ):
        try:
            run()
            print('PASS', name)
        except AssertionError as exc:
            failures += 1
            print('FAIL', name, str(exc))
    raise SystemExit(1 if failures else 0)
