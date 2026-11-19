"""Real database tests for independent controls and observed status."""
import sys
import unittest
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from datetime import timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base
from app.models import User, VkHash, AppSetting
from app.services.vk_agent_runtime import set_enabled, role_enabled, agents_status, record_activity, now_utc


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as c:
            await c.run_sync(lambda c: Base.metadata.create_all(c, tables=[User.__table__, VkHash.__table__, AppSetting.__table__]))
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_legacy_enabled_defaults_both_roles_on(self):
        self.db.add(AppSetting(key='vk_agent_enabled', value='true'))
        await self.db.commit()
        self.assertTrue(await role_enabled(self.db, 'issuer'))
        self.assertTrue(await role_enabled(self.db, 'checker'))

    async def test_turning_on_checker_does_not_start_issuer(self):
        await set_enabled(self.db, 'checker', True)
        self.assertTrue(await role_enabled(self.db, 'checker'))
        self.assertFalse(await role_enabled(self.db, 'issuer'))

    async def test_turning_off_issuer_does_not_stop_checker(self):
        await set_enabled(self.db, None, True)
        await set_enabled(self.db, 'issuer', False)
        self.assertTrue(await role_enabled(self.db, 'checker'))
        self.assertFalse(await role_enabled(self.db, 'issuer'))

    async def test_legacy_stop_disables_both(self):
        await set_enabled(self.db, None, True)
        await set_enabled(self.db, None, False)
        self.assertFalse(await role_enabled(self.db, 'checker'))
        self.assertFalse(await role_enabled(self.db, 'issuer'))

    async def test_enabled_without_heartbeat_does_not_claim_running(self):
        await set_enabled(self.db, None, True)
        status = await agents_status(self.db)
        self.assertEqual(status['agents']['checker']['state'], 'unknown')

    async def test_checker_flood_does_not_pause_issuer(self):
        await set_enabled(self.db, None, True)
        await record_activity(self.db, 'issuer', state='waiting')
        self.db.add(AppSetting(key='vk_hash_probe_until', value=(now_utc()+timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S UTC')))
        await self.db.commit()
        status = await agents_status(self.db)
        self.assertEqual(status['agents']['checker']['state'], 'cooldown')
        self.assertEqual(status['agents']['issuer']['state'], 'waiting')

    async def test_stop_during_cycle_reports_finishing(self):
        await set_enabled(self.db, None, True)
        await record_activity(self.db, 'checker', state='running')
        await set_enabled(self.db, 'checker', False)
        status = await agents_status(self.db)
        self.assertEqual(status['agents']['checker']['state'], 'stopping')

    async def test_old_heartbeat_is_not_reported_running(self):
        await set_enabled(self.db, None, True)
        await record_activity(self.db, 'checker', state='running')
        row = await self.db.get(AppSetting, 'vk_runtime_checker')
        runtime = json.loads(row.value)
        runtime['observed_at'] = (now_utc()-timedelta(minutes=10)).isoformat()
        row.value = json.dumps(runtime)
        await self.db.commit()
        self.assertEqual((await agents_status(self.db))['agents']['checker']['state'], 'stale')

    async def test_control_endpoint_changes_only_selected_worker(self):
        from app.api.admin import vk_agent_control, VkAgentControlRequest
        await set_enabled(self.db, None, True)
        status = await vk_agent_control('issuer', VkAgentControlRequest(enabled=False), True, self.db)
        self.assertFalse(status['agents']['issuer']['enabled'])
        self.assertTrue(status['agents']['checker']['enabled'])

    async def test_run_endpoint_respects_vk_pause_and_does_not_queue_work(self):
        from fastapi import BackgroundTasks, HTTPException
        from app.api.admin import vk_agent_run_once
        await set_enabled(self.db, None, True)
        self.db.add(AppSetting(key='vk_hash_probe_until', value=(now_utc()+timedelta(minutes=20)).isoformat()))
        await self.db.commit()
        tasks = BackgroundTasks()
        with self.assertRaises(HTTPException) as error:
            await vk_agent_run_once('checker', tasks, True, self.db)
        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(len(tasks.tasks), 0)

    async def test_run_endpoint_queues_exact_role_without_synchronous_vk_call(self):
        from fastapi import BackgroundTasks
        from app.api.admin import vk_agent_run_once
        await set_enabled(self.db, None, True)
        tasks = BackgroundTasks()
        await vk_agent_run_once('issuer', tasks, True, self.db)
        self.assertEqual(len(tasks.tasks), 1)
        self.assertEqual(tasks.tasks[0].args, ('issuer',))

    async def test_paused_worker_does_not_execute_cycle(self):
        from app.services.vk_agent_runtime import tracked_cycle
        @asynccontextmanager
        async def lease(name): yield True
        await set_enabled(self.db, None, True)
        await set_enabled(self.db, 'issuer', False)
        operation = AsyncMock()
        with patch('ai.vk_agent_lock.agent_lease', lease):
            await tracked_cycle(self.db, 'issuer', operation, delay=30)
        operation.assert_not_awaited()
        self.assertTrue(await role_enabled(self.db, 'checker'))

    async def test_flood_attempt_does_not_replace_cumulative_success_count(self):
        from app.services.vk_agent_runtime import tracked_cycle
        @asynccontextmanager
        async def lease(name): yield True
        await set_enabled(self.db, None, True)
        operation = AsyncMock(side_effect=[
            'liveness: 8/8 проб alive=8 pending=0 marked_dead=0 skip=0',
            'liveness: 1/8 проб alive=0 pending=0 marked_dead=0 skip=0 (preview flood)',
        ])
        with patch('ai.vk_agent_lock.agent_lease', lease):
            await tracked_cycle(self.db, 'checker', operation, delay=5)
            await tracked_cycle(self.db, 'checker', operation, delay=5)
        checker = (await agents_status(self.db))['agents']['checker']
        self.assertEqual(checker['totals']['successful'], 8)
        self.assertEqual(checker['totals']['attempted'], 9)
        self.assertEqual(checker['totals']['limited'], 1)
        self.assertEqual(checker['last_successful_batch']['alive'], 8)


if __name__ == '__main__': unittest.main()
