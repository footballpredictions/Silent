"""Real ASGI failover, encrypted fixtures and legacy DTO compatibility; no live VPS."""
from __future__ import annotations

import asyncio
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import sys
import time
import unittest
from unittest.mock import patch, AsyncMock
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'cell-agent')]
import bcrypt
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import httpx
import standby_runtime as runtime
from standby_api import OfflineSnapshot
from app.schemas.vpn import VpnConfigResponse, VpnServersResponse
from app.schemas.user import UserProfileResponse
from app.services.standby_auth_grants import standby_scope_allows

UID, DID, CID = (str(uuid.uuid4()) for _ in range(3))
PASSWORD_HASH = bcrypt.hashpw(b'fixture-password', bcrypt.gensalt(rounds=4)).decode()


def fixture():
    now = int(time.time())
    profile = {'id':UID, 'email':'fixture@example.org', 'display_id':'test',
               'subscription':{'is_active':True}, 'devices':[], 'devices_count':1}
    user = {'id':UID,'email':'fixture@example.org','active':True,'verified':True,
            'password_hash':PASSWORD_HASH,'vpn_allowed':True,'subscription_until':now+200,
            'profile':profile,'vk_hashes':['fixture-hash'],'stream_count':9,
            'tokens':{'access_token':'recovery-access','refresh_token':'recovery-refresh','token_type':'bearer'}}
    node = {'id':CID,'public_ip':'192.0.2.20','wg_public_key':'A'*43+'=',
            'wdtt_port':44444,'wg_dns':'1.1.1.1','wg_mtu':1280,'status':'active',
            'name':'Сервер 2','admin_only':False,'ai_exit':False,'api_url':'http://192.0.2.20:9100'}
    device = {'id':DID,'user_id':UID,'fingerprint':'known-device','active':True,
              'wg_private_key':'B'*43+'=','wg_public_key':'C'*43+'=',
              'wg_address':'10.66.66.22/32','wdtt_password':'fixture-only', 'preferred_server':'server2'}
    grants = {sha256(token.encode()).hexdigest():{'user_id':UID,'type':kind,'exp':now+200}
              for token,kind in [('legacy-access','access'),('legacy-refresh','refresh'),
                                  ('recovery-access','access'),('recovery-refresh','refresh')]}
    return {'schema':1,'cell_id':CID,'issued_at':now,'valid_until':now+300,
            'users':{UID:user},'devices':{DID:device},'servers':{'server2':node,'server3':{**node,'public_ip':'192.0.2.30'}},
            'grants':grants,'theme':{'app_name':'fixture'}}


class FailoverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.data = fixture()
        self.key = Fernet.generate_key()
        self.manifest = {'cell_id':CID}
        self.seal()
        self.offline = OfflineSnapshot(lambda:self.manifest, lambda:self.key)
        self.app = FastAPI()
        runtime.mount_failover_routes(self.app)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://cell.fixture')
        self.patches = [patch.object(runtime,'_offline_api',self.offline,create=True),
                        patch.object(runtime,'_proxy_queen',side_effect=httpx.ConnectError('fixture outage'))]
        for p in self.patches:p.start()

    def seal(self):
        self.manifest['offline_api'] = {'schema':1,'ciphertext':Fernet(self.key).encrypt(json.dumps(self.data).encode()).decode()}

    async def asyncTearDown(self):
        await self.client.aclose()
        for p in reversed(self.patches):p.stop()

    async def get(self, path, token='legacy-access'):
        return await self.client.get('/api/'+path,headers={'Authorization':'Bearer '+token})

    async def post(self,path,body,token='legacy-access'):
        return await self.client.post('/api/'+path,json=body,headers={'Authorization':'Bearer '+token})

    async def test_existing_config_works_during_real_proxy_exception(self):
        r = await self.get('vpn/config?fingerprint=known-device&preferred_server=server3')
        self.assertEqual(r.status_code,200,r.text)
        dto = VpnConfigResponse.model_validate(r.json())
        self.assertEqual((dto.selected_server,dto.server_ip,dto.stream_count),('server3','192.0.2.30',9))

    async def test_old_register_returns_same_device_without_allocating(self):
        r = await self.post('vpn/device/register',{'device_fingerprint':'known-device','preferred_server':'server2'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(str(VpnConfigResponse.model_validate(r.json()).device_id),DID)
        r = await self.post('vpn/device/register',{'device_fingerprint':'new-device'})
        self.assertEqual(r.status_code,503)
        self.assertEqual(len(self.data['devices']),1)

    async def test_existing_account_login_and_refresh(self):
        r = await self.post('auth/login',{'email':'FIXTURE@example.org','password':'fixture-password',
                                        'device':{'device_fingerprint':'known-device'}})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['access_token'],'recovery-access')
        r = await self.post('auth/refresh',{'refresh_token':'legacy-refresh'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['refresh_token'],'legacy-refresh')

    async def test_healthy_proxy_is_untouched_including_denials(self):
        for status in (200,401,403,429):
            with patch.object(runtime,'_proxy_queen',return_value=JSONResponse({'central':True},status_code=status)):
                r = await self.get('vpn/config?fingerprint=known-device')
                self.assertEqual((r.status_code,r.json()),(status,{'central':True}))

    async def test_confirmed_outage_does_not_repeat_upstream_timeout(self):
        with patch.object(runtime,'_queen_healthy',False),patch.object(runtime,'_proxy_queen',side_effect=AssertionError('must use ready local snapshot')):
            r=await self.get('vpn/config?fingerprint=known-device')
            self.assertEqual(r.status_code,200,r.text)

    async def test_central_503_with_body_uses_recovery(self):
        with patch.object(runtime,'_proxy_queen',return_value=JSONResponse({'detail':'outage'},status_code=503)):
            r = await self.get('vpn/config?fingerprint=known-device')
            self.assertEqual(r.status_code,200,r.text)

    async def test_unknown_token_never_logs_legacy_client_out(self):
        r = await self.get('vpn/config?fingerprint=known-device',token='unobserved-or-forged')
        self.assertEqual(r.status_code,503)

    async def test_ownership_is_required(self):
        self.data['devices'][DID]['user_id'] = str(uuid.uuid4());self.seal()
        r = await self.get('vpn/config?fingerprint=known-device')
        self.assertEqual(r.status_code,503)

    async def test_revocation_and_subscription_gates(self):
        for field in ('active','vpn_allowed','verified'):
            self.data = fixture();self.data['users'][UID][field] = False;self.seal()
            r = await self.get('vpn/config?fingerprint=known-device')
            self.assertEqual(r.status_code,403,(field,r.text))
        self.data = fixture();self.data['users'][UID]['subscription_until']=time.time()-1;self.seal()
        self.assertEqual((await self.get('vpn/config?fingerprint=known-device')).status_code,403)

    async def test_expired_or_wrong_cell_or_tampered_snapshot_fails_closed(self):
        for change in ('expired','binding','tampered','missing'):
            self.data=fixture()
            if change=='expired':self.data['valid_until']=time.time()-1
            if change=='binding':self.data['cell_id']='wrong-cell'
            self.seal()
            if change=='tampered':self.manifest['offline_api']['ciphertext']='bad'
            if change=='missing':self.manifest.pop('offline_api')
            self.assertEqual((await self.get('vpn/config?fingerprint=known-device')).status_code,503,change)

    async def test_login_rejects_wrong_password_and_new_device(self):
        r = await self.post('auth/login',{'email':'fixture@example.org','password':'wrong'})
        self.assertEqual(r.status_code,401)
        r = await self.post('auth/login',{'email':'fixture@example.org','password':'fixture-password',
                                        'device':{'device_fingerprint':'new-device'}})
        self.assertEqual(r.status_code,503)

    async def test_server_select_profile_and_hashes_legacy_shapes(self):
        r = await self.post('vpn/servers/select',{'device_fingerprint':'known-device','preferred_server':'server3'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(VpnServersResponse.model_validate(r.json()).selected_server,'server3')
        r = await self.get('users/me');self.assertEqual(r.status_code,200,r.text)
        UserProfileResponse.model_validate(r.json())
        r = await self.get('vpn/hashes');self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['hashes'],['fixture-hash'])

    async def test_ai_version_and_admin_gates_preserved(self):
        self.data['servers']['server3']['ai_exit']=True;self.seal()
        self.assertEqual((await self.get('vpn/config?fingerprint=known-device&preferred_server=server3&app_version=1.0.161')).status_code,403)
        self.assertEqual((await self.get('vpn/config?fingerprint=known-device&preferred_server=server3&app_version=1.0.171')).status_code,200)
        self.data['servers']['server3']['admin_only']=True;self.seal()
        self.assertEqual((await self.get('vpn/config?fingerprint=known-device&preferred_server=server3&app_version=1.0.171')).status_code,403)

    async def test_snapshot_login_rate_limit(self):
        for _ in range(10):
            self.assertEqual((await self.post('auth/login',{'email':'fixture@example.org','password':'wrong'})).status_code,401)
        self.assertEqual((await self.post('auth/login',{'email':'fixture@example.org','password':'wrong'})).status_code,429)

    async def test_account_mutations_and_admin_never_available_offline(self):
        self.assertEqual((await self.post('users/me/password',{})).status_code,503)
        self.assertEqual((await self.get('admin/users')).status_code,404)


class ScopeTests(unittest.TestCase):
    def test_manifest_cache_detects_atomic_replacement_and_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'manifest.json'
            path.write_text('{"version":1}',encoding='utf-8')
            with patch.object(runtime,'HIVE_MANIFEST_PATH',path),patch.object(runtime,'_manifest_stamp',None):
                first=runtime._load_manifest()
                self.assertIs(runtime._load_manifest(),first)
                temporary=path.with_suffix('.new');temporary.write_text('{"version":2}',encoding='utf-8');temporary.replace(path)
                self.assertEqual(runtime._load_manifest()['version'],2)
                path.unlink();self.assertIsNone(runtime._load_manifest())

    def test_scoped_credentials_cannot_escalate(self):
        claims={'standby_until':time.time()+300,'standby_scope':'vpn-recovery-v1'}
        self.assertTrue(standby_scope_allows(claims,'GET','/api/vpn/config'))
        for method,path in [('POST','/api/users/me/password'),('GET','/api/admin/users'),('POST','/api/auth/qr/approve')]:
            self.assertFalse(standby_scope_allows(claims,method,path))
        claims['standby_until']=time.time()-1
        self.assertFalse(standby_scope_allows(claims,'GET','/api/vpn/config'))


class CentralScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_refresh_is_bounded_and_revocation_invalidates_cache(self):
        from app.services import standby_snapshot as snapshots
        with patch.object(snapshots,'_common_cache',None),patch.object(snapshots,'_common_until',0), \
             patch.object(snapshots,'_common_lock',None),patch.object(snapshots,'build_common',new_callable=AsyncMock) as build:
            build.side_effect=[{'revision':1},{'revision':2}]
            self.assertEqual(await snapshots.cached_common(None),{'revision':1})
            self.assertEqual(await snapshots.cached_common(None),{'revision':1})
            self.assertEqual(build.await_count,1)
            snapshots.invalidate_snapshot_cache()
            self.assertEqual(await snapshots.cached_common(None),{'revision':2})

    async def test_recovery_refresh_never_becomes_an_unrestricted_session(self):
        from app.api import auth
        from app.core.security import decode_token
        from app.schemas.auth import RefreshRequest
        from app.services.standby_snapshot import recovery_tokens
        until=int(time.time())+300
        pair=recovery_tokens(UID,until)
        async def execute(_):return SimpleNamespace(scalar_one_or_none=lambda:SimpleNamespace(id=UID,is_active=True))
        result=await auth.refresh(RefreshRequest(refresh_token=pair['refresh_token']),SimpleNamespace(execute=execute))
        for token in (result.access_token,result.refresh_token):
            payload=decode_token(token)
            self.assertEqual(payload['exp'],until)
            self.assertEqual(payload['standby_scope'],'vpn-recovery-v1')

    async def test_grant_store_failure_does_not_raise_into_authentication(self):
        from app.services import standby_auth_grants as grants
        with patch.object(grants,'AsyncSessionLocal',side_effect=RuntimeError('fixture store offline')):
            await grants._persist('fixture',UID,'access',time.time()+60,time.time())

    async def test_user_dependency_rejects_account_mutation_with_recovery_token(self):
        from app.core.deps import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials
        from starlette.requests import Request
        from app.services.standby_snapshot import recovery_tokens
        pair=recovery_tokens(UID,int(time.time())+300)
        async def execute(_):return SimpleNamespace(scalar_one_or_none=lambda:SimpleNamespace(id=UID,is_active=True))
        request=Request({'type':'http','method':'POST','path':'/api/users/me/password','headers':[],'query_string':b''})
        with self.assertRaises(HTTPException) as caught:
            await get_current_user(HTTPAuthorizationCredentials(scheme='Bearer',credentials=pair['access_token']),SimpleNamespace(execute=execute),request)
        self.assertEqual(caught.exception.status_code,403)


if __name__=='__main__':unittest.main()
