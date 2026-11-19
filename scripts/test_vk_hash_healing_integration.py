"""Exercise real probe/report/fill DB transitions; no VK or production database."""
from __future__ import annotations

import sys
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from ai.vk_manager import VkManager
from ai import vk_hash_liveness as live
from app.database import Base
from app.models import AppSetting, User, VkHash
from app.services.user_hash_service import get_server_hashes_for_user, report_hash_failure


class HealingTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[User.__table__, VkHash.__table__, AppSetting.__table__]))
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.user = User(email="probe@example.invalid", password_hash="test-only")
        self.db.add(self.user)
        await self.db.flush()
        self.rows = [VkHash(user_id=self.user.id, slot_index=i,
                            hash_value=f"fixture_hash_{i}", is_active=True,
                            last_error_code=0, fail_count=0) for i in range(4)]
        self.db.add_all(self.rows)
        await self.db.commit()
        self.manager = VkManager(self.db)
        self.manager._token = "test-only"
        self.manager.ensure_authenticated = AsyncMock(return_value=(True, "OK"))
        self.manager.authenticate = AsyncMock(return_value=True)
        self.manager._get_session = AsyncMock(return_value=object())
        self.manager.create_call = AsyncMock(return_value="replacement_fixture_hash")
        self.no_sleep = patch("ai.vk_manager.asyncio.sleep", new=AsyncMock())
        self.no_sleep.start()
        @asynccontextmanager
        async def lease(name):
            yield True
        self.lease_patch = patch("ai.vk_agent_lock.agent_lease", lease)
        self.lease_patch.start()

    async def asyncTearDown(self):
        self.lease_patch.stop()
        self.no_sleep.stop()
        await self.db.close()
        await self.engine.dispose()

    async def cycle(self, target_kind):
        target_hash = self.rows[0].hash_value
        class Prober:
            flood = False
            def __init__(self, session):
                pass
            async def probe(self, value):
                return target_kind if value == target_hash else live.KIND_ALIVE
        with patch.object(live, "JoinHashProber", Prober):
            await self.manager.check_and_heal()

    async def test_two_confirmations_replace_only_dead_slot_and_client_gets_it(self):
        original = [h.hash_value for h in self.rows]
        original_ids = [h.id for h in self.rows]
        await self.cycle(live.KIND_DEAD)
        self.assertTrue(self.rows[0].is_active)
        self.assertEqual(self.rows[0].last_error_code, live.ERROR_PROBE_PENDING)
        self.manager.create_call.assert_not_awaited()
        await self.cycle(live.KIND_DEAD)
        self.manager.create_call.assert_awaited_once()
        self.assertEqual([h.id for h in self.rows], original_ids)
        self.assertEqual(await get_server_hashes_for_user(self.db, self.user),
                         ["replacement_fixture_hash", *original[1:]])
        self.assertTrue(all(h.is_active for h in self.rows))
        self.assertEqual(self.rows[0].fail_count, 0)
        status = await self.db.get(AppSetting, "vk_agent_last_message")
        self.assertIn("marked_dead=1", status.value)
        self.assertIn("+1", status.value)

    async def test_temporary_preview_failure_never_replaces(self):
        for _ in range(6):
            await self.cycle(live.KIND_SKIP)
        self.manager.create_call.assert_not_awaited()
        self.assertTrue(all(h.is_active for h in self.rows))

    async def test_busy_preview_lease_prevents_duplicate_vk_requests(self):
        @asynccontextmanager
        async def busy(name):
            yield False
        with patch("ai.vk_agent_lock.agent_lease", busy):
            result = await self.manager.probe_active_hashes()
        self.assertIn("занята", result)
        self.manager._get_session.assert_not_awaited()

    async def test_continuous_checker_reuses_valid_anonymous_token_between_batches(self):
        import asyncio
        from ai import vk_hash_monitor
        self.db.add(AppSetting(key='vk_agent_enabled', value='true'))
        await self.db.commit()
        calls = []
        batches = 0
        async def post(prober, url):
            if '/auth.getAnonymToken' in url:
                calls.append('anonymous_token')
                return {'response': {'token': 'test-valid-token'}}
            calls.append('preview')
            return {'response': {'user_id': 1}}
        @asynccontextmanager
        async def session(): yield self.db
        async def sleep(delay):
            nonlocal batches
            if delay == vk_hash_monitor.BATCH_PAUSE_SECONDS:
                batches += 1
                if batches == 2:
                    raise asyncio.CancelledError()
        with patch.object(vk_hash_monitor, 'AsyncSessionLocal', session), \
             patch.object(live.JoinHashProber, '_post', post), \
             patch('ai.vk_hash_monitor.asyncio.sleep', sleep):
            with self.assertRaises(asyncio.CancelledError):
                await vk_hash_monitor.monitor_loop()
        self.assertEqual(calls.count('preview'), 8)
        self.assertEqual(calls.count('anonymous_token'), 1,
                         'A valid anonymous token must survive the next scheduled batch')
        from app.services.vk_agent_runtime import agents_status
        status = await agents_status(self.db)
        self.assertEqual(status['agents']['checker']['totals']['successful'], 8)

    async def test_preview_of_old_hash_cannot_mark_replacement_suspicious(self):
        db = self.db
        row = self.rows[0]
        class Prober:
            flood = False
            def __init__(self, session): pass
            async def probe(self, value):
                if value == 'fixture_hash_0':
                    row.hash_value = 'new_replacement_fixture'
                    await db.commit()
                    return live.KIND_DEAD
                return live.KIND_ALIVE
        with patch.object(live, 'JoinHashProber', Prober):
            await self.manager.probe_active_hashes()
        self.assertEqual(row.hash_value, 'new_replacement_fixture')
        self.assertEqual(row.last_error_code, 0)
        self.assertTrue(row.is_active)

    async def test_cached_token_refreshes_only_when_vk_reports_expired(self):
        prober = live.JoinHashProber(None)
        prober._post = AsyncMock(side_effect=[
            {'response': {'token': 'fixture-old-token'}}, {'response': {'user_id': 1}},
            {'error': {'error_code': 100, 'error_msg': 'anonym_token.outdated'}},
            {'response': {'token': 'fixture-fresh-token'}}, {'response': {'user_id': 1}},
        ])
        self.assertEqual(await prober.probe('fixture_hash_0'), live.KIND_ALIVE)
        identity = prober._device_id
        prober.begin_batch()
        self.assertEqual(await prober.probe('fixture_hash_1'), live.KIND_ALIVE)
        self.assertEqual(prober._device_id, identity)
        self.assertEqual(sum('/auth.getAnonymToken' in call.args[0] for call in prober._post.await_args_list), 2)

    async def test_client_reports_request_probe_but_cannot_kill_a_hash(self):
        for _ in range(6):
            ok, _ = await report_hash_failure(self.db, self.user, self.rows[0].hash_value,
                                               "no_connections", "No connections")
            self.assertTrue(ok)
        self.assertTrue(self.rows[0].is_active, "client reports must not deactivate without VK confirmation")
        self.assertNotEqual(self.rows[0].last_error_code, live.ERROR_PROBE_PENDING)
        await self.cycle(live.KIND_ALIVE)
        self.manager.create_call.assert_not_awaited()
        self.assertEqual(self.rows[0].fail_count, 0)

    async def test_ambiguous_prefix_does_not_report_against_arbitrary_slot(self):
        ok, _ = await report_hash_failure(self.db, self.user, "fixture_hash_", "hash_dead", "call not found")
        self.assertFalse(ok)
        self.assertTrue(all(h.fail_count == 0 for h in self.rows))

    async def test_client_dead_reports_do_not_count_as_server_confirmation(self):
        for _ in range(6):
            await report_hash_failure(self.db, self.user, self.rows[0].hash_value,
                                      "hash_dead", "call not found")
        await self.cycle(live.KIND_DEAD)
        self.manager.create_call.assert_not_awaited()
        await self.cycle(live.KIND_DEAD)
        self.manager.create_call.assert_awaited_once()

    async def test_preview_flood_pauses_probe_without_replacing_healthy_slots(self):
        await self.cycle(live.KIND_FLOOD)
        self.manager.create_call.assert_not_awaited()
        pause = await self.db.get(AppSetting, live.SETTING_PROBE_UNTIL)
        self.assertIsNotNone(pause)
        self.assertTrue(all(h.is_active for h in self.rows))
        interval = await self.db.get(AppSetting, live.SETTING_PROBE_INTERVAL)
        self.assertGreaterEqual(float(interval.value), 30)

    async def test_pending_then_alive_recovers_without_replacement(self):
        await self.cycle(live.KIND_DEAD)
        await self.cycle(live.KIND_SKIP)
        await self.cycle(live.KIND_ALIVE)
        self.assertEqual(self.rows[0].last_error_code, 0)
        self.manager.create_call.assert_not_awaited()

    async def test_unique_legacy_prefix_queues_probe_without_claiming_checked(self):
        self.rows[0].hash_value = "unique_prefix_fixture"
        await self.db.commit()
        ok, _ = await report_hash_failure(self.db, self.user, "unique_prefix", "hash_dead", "call not found")
        self.assertTrue(ok)
        self.assertEqual(self.rows[0].fail_count, 1)
        self.assertIsNone(self.rows[0].last_checked)

    async def test_checker_hands_persisted_dead_slot_to_separate_issuer(self):
        from ai.vk_hash_monitor import run_probe_cycle
        from ai.tunnel_monitor import run_heal_cycle
        class Prober:
            flood = False
            def __init__(self, session):
                pass
            async def probe(self, value):
                return live.KIND_DEAD if value == "fixture_hash_0" else live.KIND_ALIVE
        self.db.add(AppSetting(key="vk_agent_enabled", value="true"))
        await self.db.commit()
        with patch.object(live, "JoinHashProber", Prober), \
             patch("ai.vk_hash_monitor.VkManager", return_value=self.manager):
            await run_probe_cycle(self.db)
            await run_probe_cycle(self.db)
        self.assertFalse(self.rows[0].is_active)
        self.manager.create_call.assert_not_awaited()
        with patch("ai.tunnel_monitor.VkManager", return_value=self.manager):
            await run_heal_cycle(self.db, full_fill=False)
        self.manager.create_call.assert_awaited_once()
        self.assertEqual(await get_server_hashes_for_user(self.db, self.user),
                         ["replacement_fixture_hash", "fixture_hash_1", "fixture_hash_2", "fixture_hash_3"])


class QueueTest(unittest.TestCase):
    def test_pending_backlog_cannot_starve_reports_or_routine_sweep(self):
        rows = [SimpleNamespace(id=f"pending-{i}", last_error_code=2, fail_count=1, last_checked=None)
                for i in range(20)]
        complaint = SimpleNamespace(id="complaint", last_error_code=0, fail_count=1, last_checked=None)
        routine = SimpleNamespace(id="routine", last_error_code=0, fail_count=0, last_checked=None)
        batch = live.select_probe_batch([*rows, complaint, routine], None, 8)
        self.assertIn(complaint, batch)
        self.assertIn(routine, batch)

    def test_reports_keep_priority_after_cursor(self):
        old = datetime.utcnow() - timedelta(days=1)
        complaint = SimpleNamespace(id="a", last_error_code=0, fail_count=1, last_checked=old)
        cursor = SimpleNamespace(id="b", last_error_code=0, fail_count=0, last_checked=old)
        healthy = SimpleNamespace(id="c", last_error_code=0, fail_count=0, last_checked=old)
        self.assertIs(live.select_probe_batch([complaint, cursor, healthy], "b", 1)[0], complaint)

    def test_skipped_pending_cannot_starve_other_pending_forever(self):
        oldest = datetime.utcnow() - timedelta(days=1)
        rows = [SimpleNamespace(id=str(i), last_error_code=2, fail_count=1, last_checked=oldest)
                for i in range(10)]
        first = live.select_probe_batch(rows, None, 8)
        for row in first:
            row.last_checked = datetime.utcnow()
        second = live.select_probe_batch(rows, str(first[-1].id), 8)
        self.assertEqual({r.id for r in first + second}, {r.id for r in rows})


if __name__ == "__main__":
    unittest.main()
