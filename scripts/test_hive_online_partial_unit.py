"""Real collection -> assembly -> shared dashboard read with missing node status."""
import asyncio
from contextlib import ExitStack
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models import HiveCell
from app.services import hive_online_snapshot as snapshots, hive_service as svc, wg_peer_gc


class MemoryRedis:
    def __init__(self): self.data = {}
    async def get(self, key): return self.data.get(key)
    async def set(self, key, value, **kw): self.data[key] = value
    def pipeline(self, **kw): return Pipeline(self)


class Pipeline:
    def __init__(self, redis): self.redis, self.ops = redis, []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def watch(self, key): pass
    async def get(self, key): return await self.redis.get(key)
    def multi(self): pass
    def set(self, key, value, **kw): self.ops.append(('set', key, value))
    def delete(self, key): self.ops.append(('delete', key, None))
    async def execute(self):
        for op, key, value in self.ops:
            if op == 'set': self.redis.data[key] = value
            else: self.redis.data.pop(key, None)


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now, self.failed = 1_000_000.0, set()
        self.redis = MemoryRedis()
        snapshots._cached = None
        svc._SHOWN_ONLINE_AT = 0
        self.cells = [HiveCell(id=uuid.uuid4(), name=name, is_queen=queen,
            public_ip='192.0.2.1', status='active', priority=1, max_clients=100,
            wdtt_port=56000, wg_port=51820, accepts_wdtt=True, admin_only=False, ai_exit=False)
            for name, queen in [('Queen', True), ('Cell1', False), ('Cell2', False), ('Cell3', False), ('Cell4', False)]]
        self.counts = dict(zip([c.id for c in self.cells], [17, 1, 2, 2, 17]))
        self.loads = dict(zip([c.id for c in self.cells], [43, 30, 32, 12, 15]))
        async def online(_): return self.counts, sum(self.counts.values())
        async def olc(*_): return {}
        async def assigned(*_): return 1
        async def capacity(*_, **kw): return SimpleNamespace(to_dict=lambda: {'max_online': 100})
        async def fetch(cell, **kw):
            return None if cell.id in self.failed else {'wg_peers_live_3m': self.loads[cell.id]}
        self.stack = ExitStack()
        for p in (patch.object(svc, 'connected_devices_by_cell', online),
                  patch.object(svc, 'olcrtc_online_by_cell', olc),
                  patch.object(svc, 'count_assigned_on_cell', assigned),
                  patch.object(svc, 'get_capacity_profile', capacity),
                  patch.object(svc, '_get_shown_redis', return_value=self.redis),
                  patch.object(svc, 'fetch_worker_cell_load', fetch),
                  patch.object(wg_peer_gc, 'queen_wg_peer_counts', side_effect=lambda: {'wg_peers_live_3m': self.loads[self.cells[0].id]}),
                  patch.object(snapshots.time, 'time', side_effect=lambda: self.now)):
            self.stack.enter_context(p)
        self.addCleanup(self.stack.close)

    async def collect(self):
        loads = await svc._worker_loads_for_cells(self.cells, timeout=2)
        return await svc._assemble_cells_with_stats(None, self.cells, loads, {})

    async def test_one_missing_measurement_does_not_publish_134_to_105(self):
        await self.collect()
        self.failed.add(self.cells[1].id)
        rows = await self.collect()
        self.assertEqual(await svc._redis_get_shown(), 134)
        self.assertEqual(rows[1]['online_count'], 30)
        self.assertEqual(rows[1]['online_status'], 'stale')

    async def test_other_worker_uses_shared_last_good(self):
        await self.collect()
        snapshots._cached = None
        svc._SHOWN_ONLINE_AT = 0
        self.failed.add(self.cells[1].id)
        await self.collect()
        self.assertEqual(await svc.cached_vpn_online_shown_shared(), 134)

    async def test_repeated_failures_do_not_renew_measurement_age(self):
        await self.collect()
        self.failed.add(self.cells[1].id)
        start = self.now
        for age in (30, 60, 89):
            self.now = start + age
            await self.collect()
            self.assertEqual(await svc._redis_get_shown(), 134)
        self.now = start + 91
        await self.collect()
        self.assertIsNone(await svc._redis_get_shown())
        self.assertIsNone(await svc.vpn_online_shown_total(None, soft=True))
        self.assertEqual(snapshots.metadata()['online_unknown_nodes'], ['Cell1'])

    async def test_fresh_zero_and_decrease_are_not_smoothed(self):
        await self.collect()
        self.loads[self.cells[1].id] = 0
        self.counts[self.cells[1].id] = 0
        await self.collect()
        self.assertEqual(await svc._redis_get_shown(), 104)
        self.assertEqual(snapshots.metadata()['online_status'], 'fresh')

    async def test_reading_old_snapshot_never_renews_its_lifetime(self):
        await self.collect()
        self.now += 91
        for _ in range(3):
            self.assertIsNone(await svc.cached_vpn_online_shown_shared())
        self.assertEqual(snapshots.metadata()['online_status'], 'unknown')

    async def test_cold_partial_collection_is_unknown_not_db_only(self):
        self.failed.add(self.cells[1].id)
        rows = await self.collect()
        self.assertIsNone(await svc.cached_vpn_online_shown_shared())
        self.assertEqual(rows[1]['online_status'], 'unknown')

    async def test_queen_measurement_failure_has_same_bounded_fallback(self):
        await self.collect()
        with patch.object(wg_peer_gc, 'queen_wg_peer_counts', side_effect=OSError):
            rows = await self.collect()
        self.assertEqual(await svc._redis_get_shown(), 134)
        self.assertEqual(rows[0]['online_status'], 'stale')

    async def test_real_queen_dump_failure_is_not_a_measured_zero(self):
        await self.collect()
        self.stack.enter_context(patch.object(wg_peer_gc, '_QUEEN_WG_COUNTS', None))
        with patch.object(wg_peer_gc, '_queen_wg_dump', side_effect=OSError):
            # The real function was saved before patching the collection fixture.
            counts = REAL_QUEEN_COUNTS()
        self.assertFalse(counts['wg_stats_ok'])
        with patch.object(wg_peer_gc, 'queen_wg_peer_counts', return_value=counts):
            rows = await self.collect()
        self.assertEqual(rows[0]['online_count'], 43)
        self.assertEqual(rows[0]['online_status'], 'stale')

    async def test_slow_old_collection_cannot_overwrite_newer_decrease(self):
        rows = await self.collect()
        old = json.loads(self.redis.data[snapshots.KEY])
        self.now += 10
        self.loads[self.cells[1].id] = self.counts[self.cells[1].id] = 0
        await self.collect()
        result = await snapshots.publish(self.redis, rows, old['started_at'])
        self.assertEqual(result['total'], 104)
        self.assertEqual(await svc._redis_get_shown(), 104)


REAL_QUEEN_COUNTS = wg_peer_gc.queen_wg_peer_counts
if __name__ == '__main__': unittest.main()
