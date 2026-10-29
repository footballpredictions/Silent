"""Opt-in PostgreSQL integration test. Uses only random, isolated AppSetting keys.

Run inside an API environment: python scripts/test_hive_profiles_db.py --run
No HiveCell/device rows are inserted and no host commands are executed.
"""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlalchemy import delete
from app.database import AsyncSessionLocal
from app.models import AppSetting
from app.services import hive_profiles as profiles


async def no_host(*args):
    pass


async def main():
    node = SimpleNamespace(id=uuid.uuid4(), name='profile-transaction-fixture', public_ip='198.51.100.10',
                           is_queen=True, ai_exit=False, ssh_password_enc=None, status='active')
    key = profiles.PREFIX + str(node.id)
    try:
        with patch.object(profiles, '_apply_job', no_host):
            async def request(**kw):
                async with AsyncSessionLocal() as db:
                    try:
                        return await profiles.request_change(db, node, expected_revision=0, **kw)
                    except HTTPException as e:
                        return e.status_code

            results = await asyncio.gather(request(ai=True, gaming=None), request(ai=None, gaming=True))
            assert sum(isinstance(x, dict) for x in results) == 1, results
            assert 409 in results, results
            pending = next(x for x in results if isinstance(x, dict))
            assert pending['state'] == 'running' and not pending['ai'] and not pending['gaming']
            op = pending['operation_id']
            # An old job cannot overwrite a new operation.
            await profiles._finish(node, 'stale-operation', {'state': 'applied', 'result': {'ai': True, 'gaming': True}})
            async with AsyncSessionLocal() as db:
                assert (await profiles.get_profile(db, node))['state'] == 'running'
            await profiles._finish(node, op, {'state': 'applied', 'result': pending['requested']})
            async with AsyncSessionLocal() as db:
                verified = await profiles.get_profile(db, node)
                assert verified['state'] == 'ready' and verified['revision'] == 1
                assert verified['ai'] == pending['requested']['ai']
                assert not node.ai_exit, 'profile must not change the legacy routing/security role'
                try:
                    await profiles.request_change(db, node, ai=True, gaming=True, expected_revision=0)
                    raise AssertionError('stale revision accepted')
                except HTTPException as e:
                    assert e.status_code == 409
            async with AsyncSessionLocal() as db:
                retry = await profiles.request_change(db, node, ai=True, gaming=True, expected_revision=1)
            await profiles._finish(node, retry['operation_id'], {'state': 'error', 'error': 'fixture rollback', 'rolled_back': True})
            async with AsyncSessionLocal() as db:
                failed = await profiles.get_profile(db, node)
                assert failed['state'] == 'error' and failed['rolled_back']
                assert failed['ai'] == verified['ai'] and failed['gaming'] == verified['gaming']
                assert failed['revision'] == verified['revision']
            assert profiles.decode(node, '{broken')['wg_mtu'] == 1200
            if '--http' in sys.argv:
                from fastapi import FastAPI
                import httpx
                from app.api import hive
                from app.core.deps import get_admin_credentials
                from app.database import get_db
                app = FastAPI()
                app.include_router(hive.router, prefix='/api')
                app.dependency_overrides[get_admin_credentials] = lambda: True
                async def session():
                    async with AsyncSessionLocal() as db:
                        yield db
                app.dependency_overrides[get_db] = session
                with patch.object(hive.hive_service, 'get_cell_by_id', AsyncMock(return_value=node)):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                        path = f'/api/admin/hive/cells/{node.id}/profiles'
                        assert (await client.patch(path, json={})).status_code == 422
                        response = await client.patch(path, json={'ai': True, 'gaming': True, 'expected_revision': 1})
                        assert response.status_code == 200, response.text
                        assert response.json()['profiles']['state'] == 'running'
                        assert (await client.patch(path, json={'gaming': False})).status_code == 409
                        app.dependency_overrides.pop(get_admin_credentials)
                        unauthenticated = await client.patch(path, json={'gaming': True})
                        assert unauthenticated.status_code == 401, unauthenticated.text
                print('ok: actual HTTP handler, request validation, queen without SSH, conflict and authentication')
            print('ok: PostgreSQL concurrency, pending/applied flags, stale jobs/revisions, rollback, legacy role, corrupt-setting fallback')
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == key))
            await db.commit()


if __name__ == '__main__':
    if '--run' not in sys.argv:
        raise SystemExit('Use --run in an isolated API test process')
    asyncio.run(main())
