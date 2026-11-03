"""Real SQL eligibility/jobs and host runner behavior, with no production deletion."""
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from fastapi import FastAPI
import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base
from app.models import AppSetting, Device, HiveCell, Payment, Subscription, User
from app.services import inactive_user_cleanup as users
from app.services import vps_cleanup_settings as jobs
from scripts import vps_cleanup_runner as runner
from app.services.standby_auth_grants import SCHEMA_SQL

NOW=datetime(2026,11,3,12)
OLD=NOW-timedelta(days=180)
PRESENCE={'checked':True,'nodes_checked':5,'pubs':[],'refs':[]}
REAL_STRICT_PRESENCE=users.strict_presence


class CleanupSqlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as con:
            await con.run_sync(lambda sync:Base.metadata.create_all(sync,tables=[Base.metadata.tables[name] for name in
                ('users','devices','hive_cells','subscriptions','payments','referral_rewards','vk_hashes','vk_link_sessions','app_settings')]))
            await con.execute(text(SCHEMA_SQL))
            await con.execute(text('PRAGMA foreign_keys=ON'))
        self.db=async_sessionmaker(self.engine,expire_on_commit=False)()
        self.presence=patch.object(users,'strict_presence',AsyncMock(return_value=PRESENCE.copy()))
        self.presence.start()

    async def asyncTearDown(self):
        self.presence.stop();await self.db.close();await self.engine.dispose()

    async def user(self,name='dead',**kw):
        row=User(email=name+'@example.org',password_hash='fixture',created_at=OLD,last_seen_at=OLD,**kw)
        self.db.add(row);await self.db.flush();return row

    async def device(self,user,**kw):
        row=Device(user_id=user.id,device_name='fixture',device_type='android',device_fingerprint=str(uuid.uuid4()),created_at=OLD,**kw)
        self.db.add(row);await self.db.flush();return row

    async def test_dead_deleted_with_devices_and_persistent_uuid_deny(self):
        dead=await self.user();device=await self.device(dead)
        survivor=await self.user('survivor');survivor.referred_by_user_id=dead.id;survivor.last_seen_at=NOW
        await self.db.commit()
        result=await users.delete_inactive_users(self.db,now=NOW);await self.db.commit()
        self.assertEqual((result['deleted_users'],result['deleted_devices']),(1,1))
        self.assertIsNone(await self.db.scalar(select(User.id).where(User.id==dead.id)))
        await self.db.refresh(survivor);self.assertIsNone(survivor.referred_by_user_id)
        self.assertIsNotNone(await self.db.get(AppSetting,'vpn_deleted_device:'+str(device.id)))

    async def test_every_active_subscription_is_protected(self):
        for index,plan in enumerate(('monthly','test','trial','admin_unlimited')):
            user=await self.user('paid'+str(index))
            self.db.add(Subscription(user_id=user.id,plan_type=plan,status='active',amount_paid=0,expires_at=NOW+timedelta(days=1)))
        await self.db.commit()
        self.assertEqual((await users.preview_inactive_users(self.db,now=NOW))['candidate_users'],0)
        self.assertEqual((await users.delete_inactive_users(self.db,now=NOW))['deleted_users'],0)

    async def test_admin_bootstrap_and_owner_are_protected(self):
        from app.config import settings
        from app.services.vpn_service import BOOTSTRAP_USER_EMAIL
        await self.user('admin',is_admin=True)
        for email in (settings.ADMIN_LOGIN,BOOTSTRAP_USER_EMAIL):
            row=await self.user(str(uuid.uuid4()));row.email=email
        await self.db.commit()
        self.assertEqual((await users.preview_inactive_users(self.db,now=NOW))['candidate_users'],0)

    async def test_recent_activity_payments_and_connected_flags_protect(self):
        for field in ('last_seen_at','vk_linked_at'):
            row=await self.user(field);setattr(row,field,NOW)
        for index,kw in enumerate(({'last_connected':NOW},{'is_connected':True})):
            row=await self.user('device'+str(index));await self.device(row,**kw)
        for index,kw in enumerate(({'status':'pending','created_at':OLD},{'status':'completed','created_at':NOW})):
            row=await self.user('payment'+str(index))
            self.db.add(Payment(user_id=row.id,plan_type='monthly',amount=1,wallet='fixture',yumoney_label=str(uuid.uuid4()),**kw))
        await self.db.commit()
        self.assertEqual((await users.preview_inactive_users(self.db,now=NOW))['candidate_users'],0)

    async def test_verified_tokens_protect_returning_account(self):
        row=await self.user()
        await self.db.execute(text('INSERT INTO standby_token_grants(token_hash,user_id,token_type,expires_at,seen_at) VALUES(:hash,:uid,:type,:exp,:seen)'),
            {'hash':'fixture','uid':row.id.hex,'type':'access','exp':1e12,'seen':NOW.replace(tzinfo=timezone.utc).timestamp()})
        await self.db.commit()
        self.assertEqual((await users.preview_inactive_users(self.db,now=NOW))['candidate_users'],0)

    async def test_strict_three_calendar_month_boundary_and_missing_last_seen(self):
        exact=await self.user('exact');exact.last_seen_at=users.inactivity_cutoff(NOW)
        unknown=await self.user('unknown');unknown.last_seen_at=None
        new=await self.user('new');new.created_at=NOW;new.last_seen_at=None
        await self.db.commit()
        self.assertEqual((await users.preview_inactive_users(self.db,now=NOW))['candidate_users'],1)
        self.assertEqual(users.inactivity_cutoff(datetime(2026,5,31)),datetime(2026,2,28))

    async def test_live_getconf_identity_protects_stale_database_user(self):
        row=await self.user();device=await self.device(row)
        snapshot={**PRESENCE,'refs':[device.device_fingerprint]}
        with patch.object(users,'strict_presence',AsyncMock(return_value=snapshot)):
            result=await users.delete_inactive_users(self.db,now=NOW)
        self.assertEqual(result['deleted_users'],0)
        self.assertEqual(result['protected_live_users'],1)

    async def test_unreachable_node_skips_all_deletions(self):
        row=await self.user()
        with patch.object(users,'strict_presence',AsyncMock(return_value={'checked':False,'reason':'offline'})):
            result=await users.delete_inactive_users(self.db,now=NOW)
        self.assertTrue(result['skipped']);self.assertIsNotNone(await self.db.get(User,row.id))

    async def test_presence_requires_success_from_queen_and_every_registered_cell(self):
        self.db.add(HiveCell(name='fixture',public_ip='192.0.2.1',is_queen=False,status='offline'))
        await self.db.commit()
        def node(host=None,password=None):
            if host:raise TimeoutError('fixture')
            return {'checked':True,'pubs':[],'refs':[]}
        with patch.object(users,'_read_node',side_effect=node),patch('app.services.hive_service.resolve_ssh_password',return_value='fixture'):
            snapshot=await REAL_STRICT_PRESENCE(self.db)
        self.assertFalse(snapshot['checked'])

    async def test_sql_rollback_restores_account_devices_and_deny_together(self):
        row=await self.user();device=await self.device(row)
        uid,did=row.id,device.id
        await self.db.commit()
        result=await users.delete_inactive_users(self.db,now=NOW)
        self.assertEqual(result['deleted_users'],1)
        await self.db.rollback()
        self.assertIsNotNone(await self.db.get(User,uid));self.assertIsNotNone(await self.db.get(Device,did))
        self.assertIsNone(await self.db.get(AppSetting,'vpn_deleted_device:'+str(did)))

    async def test_manual_cleanup_works_with_schedule_disabled_and_claims_once(self):
        status=await jobs.set_vps_cleanup(self.db,enabled=False,run_now=True)
        self.assertFalse(status['enabled']);self.assertEqual(status['status'],'queued')
        claim=await jobs.claim_vps_cleanup(self.db)
        self.assertTrue(claim['run']);self.assertFalse(claim['inactive_users_enabled'])
        self.assertFalse((await jobs.claim_vps_cleanup(self.db))['run'])
        result=await jobs.update_vps_cleanup_meta(self.db,run_id=claim['run_id'],summary='done',result={'freed_approx_mb':123})
        self.assertEqual(result['status'],'succeeded');self.assertEqual(result['result']['freed_approx_mb'],123)
        duplicate=await jobs.update_vps_cleanup_meta(self.db,run_id=claim['run_id'],summary='duplicate')
        self.assertEqual(duplicate['last_summary'],'done')

    async def test_wrong_run_and_disabled_account_option_cannot_delete(self):
        await jobs.set_vps_cleanup(self.db,enabled=True,run_now=True)
        claim=await jobs.claim_vps_cleanup(self.db)
        with self.assertRaises(HTTPException) as exc:
            await jobs.cleanup_inactive_users_for_job(self.db,claim['run_id'])
        self.assertEqual(exc.exception.status_code,403)
        await self.db.rollback()
        with self.assertRaises(HTTPException) as exc:
            await jobs.update_vps_cleanup_meta(self.db,run_id='stale',summary='stale')
        self.assertEqual(exc.exception.status_code,409)

    async def test_user_phase_is_idempotent_and_revocation_runs_after_commit(self):
        await self.user();await self.db.commit()
        await jobs.set_vps_cleanup(self.db,enabled=True,run_now=True,inactive_users_enabled=True)
        claim=await jobs.claim_vps_cleanup(self.db)
        with patch.object(users,'delete_inactive_users',AsyncMock(return_value={'deleted_users':0})) as remove:
            a=await jobs.cleanup_inactive_users_for_job(self.db,claim['run_id'])
            b=await jobs.cleanup_inactive_users_for_job(self.db,claim['run_id'])
        self.assertEqual(a,b);self.assertEqual(remove.await_count,1)

    async def test_real_http_routes_require_auth_and_report_job_result(self):
        from app.api.admin import router as admin_router
        from app.api.vpn import router as vpn_router
        from app.database import get_db
        from app.core.deps import get_admin_credentials
        from app.config import settings
        app=FastAPI();app.include_router(admin_router,prefix='/api');app.include_router(vpn_router,prefix='/api')
        async def database():yield self.db
        app.dependency_overrides[get_db]=database
        async def denied():raise HTTPException(401,'fixture')
        app.dependency_overrides[get_admin_credentials]=denied
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
            with patch.object(settings,'INTERNAL_API_SECRET','fixture-secret'),patch.object(jobs,'wake_vps_cleanup_host',AsyncMock()):
                self.assertEqual((await client.get('/api/admin/settings/vps-cleanup/inactive-preview')).status_code,401)
                self.assertEqual((await client.post('/api/vpn/internal/vps-cleanup/claim',json={})).status_code,403)
                app.dependency_overrides[get_admin_credentials]=lambda:True
                preview=await client.get('/api/admin/settings/vps-cleanup/inactive-preview')
                self.assertEqual(preview.status_code,200,preview.text)
                response=await client.post('/api/admin/settings/vps-cleanup',json={'enabled':False,'run_now':True})
                self.assertEqual(response.status_code,200,response.text)
                headers={'X-Internal-Secret':'fixture-secret'}
                claim=(await client.post('/api/vpn/internal/vps-cleanup/claim',json={},headers=headers)).json()
                self.assertTrue(claim['run'])
                response=await client.post('/api/vpn/internal/vps-cleanup/meta',headers=headers,json={
                    'run_id':claim['run_id'],'status':'partial','summary':'fixture partial','result':{'freed_approx_mb':17},'error':'fixture error'})
                self.assertEqual(response.status_code,200,response.text)
                data=(await client.get('/api/admin/settings/vps-cleanup')).json()
                self.assertEqual(data['status'],'partial');self.assertEqual(data['result']['freed_approx_mb'],17)


class HostRunnerTests(unittest.TestCase):
    def test_disk_only_job_never_calls_user_removal(self):
        calls=[]
        def api(path,body,**kw):
            calls.append(path)
            if path=='/claim':return {'run':True,'run_id':'fixture','journal_max_mb':200,'inactive_users_enabled':False}
        result=runner.run_job(api,lambda mb:{'freed_approx_mb':42,'steps':[{'status':'ok'}]})
        self.assertEqual(calls,['/claim','/meta']);self.assertEqual(result['status'],'succeeded')

    def test_failed_node_is_partial_and_not_a_fake_success(self):
        def api(path,body,**kw):
            if path=='/claim':return {'run':True,'run_id':'fixture','journal_max_mb':200,'inactive_users_enabled':True}
            if path=='/inactive-users':return {'skipped':True,'reason':'offline','deleted_users':0}
        result=runner.run_job(api,lambda mb:{'steps':[]})
        self.assertEqual(result['status'],'partial');self.assertEqual(result['error'],'offline')

    def test_safe_commands_never_truncate_logs_prune_volumes_or_restart(self):
        commands=[]
        with patch.object(runner,'command',side_effect=lambda args:commands.append(args) or {'status':'ok'}),patch.object(runner,'clean_old_deploy_files',return_value=0):
            runner.clean_disk(200)
        self.assertEqual(commands[0],['journalctl','--rotate'])
        flattened=' '.join(' '.join(c) for c in commands)
        for forbidden in ('truncate','volume','container prune','restart','-af'):self.assertNotIn(forbidden,flattened)


if __name__=='__main__':unittest.main()
