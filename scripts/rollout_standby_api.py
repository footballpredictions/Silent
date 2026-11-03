"""Controlled recovery rollout. Backend/bundle publication stays in deploy_stable.py.

prepare: additive schema, per-cell encryption keys, bounded auto-upgrade lease.
validate: read-only production snapshot build using local source, no publication.
cell SLOT: upgrade exactly one agent, enable its encrypted snapshot, shadow-test outage.
release: verify every agent's build and snapshot before releasing the upgrade lease.
Never stops wdtt, changes DNAT or invokes public config builders during preparation.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shlex
import sys

from _deploy_common import BACKEND_ROOT, CONTAINER, connect

PRELUDE = '''
import asyncio,json,time,io,shlex,subprocess,re
from pathlib import Path
from sqlalchemy import select,text
from app.database import AsyncSessionLocal
from app.models import AppSetting,HiveCell
from app.core.security import encrypt_value,decrypt_value
from app.services.hive_slots import slot_for_cell
from app.services.hive_service import resolve_ssh_password
from app.services.hive_provision_service import _ssh_connect,_run,upgrade_cell_agent_via_ssh,cell_agent_build_id
async def setting(db,key,value):
 row=await db.get(AppSetting,key)
 if row:row.value=value
 else:db.add(AppSetting(key=key,value=value))
async def workers(db):
 return list((await db.execute(select(HiveCell).where(HiveCell.is_queen==False,HiveCell.status.in_(('active','draining'))))).scalars())
def remote(ssh,program,timeout=40):
 code,out,err=_run(ssh,'/opt/silent-vpn/cell-agent/venv/bin/python -c '+shlex.quote(program),timeout=timeout)
 if code:
  safe=re.sub(r'[A-Za-z0-9_-]{12,}\\.[A-Za-z0-9_-]{12,}\\.[A-Za-z0-9_-]{12,}','<REDACTED-JWT>',(err or out)[-1200:])
  raise RuntimeError('node check failed: '+safe)
 # _run uses a PTY: standard logging is merged with stdout.
 rows=[line.strip() for line in out.splitlines() if line.strip().startswith('{')]
 if not rows:raise RuntimeError('node check returned no JSON summary')
 return json.loads(rows[-1])
'''

PROBE = '''
import json,subprocess,pathlib,time
def cmd(*args):
 p=subprocess.run(args,capture_output=True,text=True,timeout=10,check=True);return p.stdout.strip()
peers={}
iface=cmd('wg','show','interfaces').split()[0]
for line in cmd('wg','show',iface,'dump').splitlines()[1:]:
 f=line.split('\t')
 if len(f)>=8:peers[f[0]]={'allowed':f[3],'live':int(f[4])>time.time()-180}
state=json.loads(pathlib.Path('/etc/wdtt/standby_mode.json').read_text())
print(json.dumps({'wdtt':cmd('systemctl','show','wdtt','-p','MainPID','-p','NRestarts','-p','ActiveState'),
 'agent':cmd('systemctl','is-active','silent-cell-agent'),
 'agent_pid':cmd('systemctl','show','silent-cell-agent','-p','MainPID','--value'),'peers':peers,
 'ifindex':pathlib.Path('/sys/class/net',iface,'ifindex').read_text().strip(),
 'standby':state.get('standby_active'),
 'nat':cmd('iptables','-t','nat','-S','PREROUTING')}))
'''

SHADOW = '''
import asyncio,json,sys,time
sys.path.insert(0,'/opt/silent-vpn/cell-agent')
from unittest.mock import patch
from fastapi import FastAPI
import httpx
import standby_runtime as runtime
async def main():
 data=runtime._offline_api.read()
 candidates=[(d,data['users'][d['user_id']]) for d in data['devices'].values()
   if d['active'] and data['users'].get(d['user_id'],{}).get('vpn_allowed')
   and d.get('wg_private_key') and d.get('wdtt_password')]
 assert candidates,'no recoverable registered devices'
 manifest=runtime._load_manifest()
 slot=manifest.get('slot') or next(k for k,v in data['servers'].items() if v['id']==manifest['cell_id'])
 candidates=[(d,u) for d,u in candidates if not data['servers'][slot].get('admin_only') or u.get('is_admin')]
 assert candidates,'no eligible local devices'
 device,user=candidates[0]
 app=FastAPI();runtime.mount_failover_routes(app)
 statuses={}
 with patch.object(runtime,'_proxy_queen',side_effect=httpx.ConnectError('isolated shadow outage')):
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://shadow') as c:
   h={'Authorization':'Bearer '+user['tokens']['access_token']}
   r=await c.get('/api/vpn/config',params={'fingerprint':device['fingerprint'],'preferred_server':slot,'app_version':'1.0.171'},headers=h)
   statuses['config']=r.status_code
   assert r.status_code==200 and r.json().get('selected_server')==slot,('config status',r.status_code)
   assert r.json()['device_id']==device['id']
   r=await c.post('/api/auth/refresh',json={'refresh_token':user['tokens']['refresh_token']})
   statuses['refresh']=r.status_code;assert r.status_code==200
   r=await c.get('/api/vpn/config',params={'fingerprint':device['fingerprint']},headers={'Authorization':'Bearer forged'})
   statuses['unknown_token']=r.status_code;assert r.status_code==503
   if globals().get('LEGACY_TOKEN'):
    r=await c.get('/api/vpn/hashes',headers={'Authorization':'Bearer '+LEGACY_TOKEN})
    statuses['legacy_access']=r.status_code
    if r.status_code!=200:
     from hashlib import sha256
     latest=runtime._offline_api.read();grant=latest['grants'].get(sha256(LEGACY_TOKEN.encode()).hexdigest())
     assert False,('legacy_access',r.status_code,'grant_present',bool(grant),
                   'grant_type',grant.get('type') if grant else None,
                   'valid_for',round(grant['exp']-time.time()) if grant else None,
                   'detail',r.json().get('detail'))
 print(json.dumps({'slot':slot,'users':len(data['users']),'devices':len(data['devices']),
  'grants':len(data['grants']),'snapshot_age_sec':round(time.time()-data['issued_at'],1),
  'node_epoch':time.time(),'valid_for_sec':round(data['valid_until']-time.time()),'shadow':statuses}))
asyncio.run(main())
'''


def source_for(action, slot):
    if action=='prepare':
        # Schema is deliberately independent of the not-yet-published module.
        import ast
        tree=ast.parse((BACKEND_ROOT/'app/services/standby_auth_grants.py').read_text(encoding='utf-8'))
        schema=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCHEMA_SQL' for t in n.targets))
        return PRELUDE+f'SCHEMA={schema!r}\n'+'''
from cryptography.fernet import Fernet
async def main():
 async with AsyncSessionLocal() as db:
  await db.execute(text(SCHEMA))
  await db.execute(text('CREATE INDEX IF NOT EXISTS ix_standby_grants_user ON standby_token_grants(user_id)'))
  await setting(db,'standby_agent_rollout_hold_until',str(time.time()+1800))
  nodes=await workers(db)
  for node in nodes:
   name='standby_offline_key_v1:'+str(node.id)
   record=await db.get(AppSetting,name)
   key=decrypt_value(record.value).encode() if record else Fernet.generate_key()
   Fernet(key)
   ssh=_ssh_connect(node.public_ip,resolve_ssh_password(node),timeout=8)
   try:
    with ssh.open_sftp() as sftp:
     temp='/etc/wdtt/standby_api.key.new'
     with sftp.file(temp,'wb') as f:f.write(key)
     sftp.chmod(temp,0o600);sftp.posix_rename(temp,'/etc/wdtt/standby_api.key')
   finally:ssh.close()
   if not record:await setting(db,name,encrypt_value(key.decode()))
  await db.commit()
 print(json.dumps({'prepared_cells':len(nodes),'feature_enabled':False,'rollout_hold_sec':1800}))
asyncio.run(main())
'''
    if action=='validate':
        src=(BACKEND_ROOT/'app/services/standby_snapshot.py').read_text(encoding='utf-8')
        return PRELUDE+f'SOURCE={src!r}\n'+'''
async def main():
 namespace={};exec(compile(SOURCE,'standby_snapshot.py','exec'),namespace)
 async with AsyncSessionLocal() as db:
  await db.execute(text('SET TRANSACTION READ ONLY'))
  start=time.monotonic();data=await namespace['build_common'](db)
  from app.schemas.user import UserProfileResponse
  for user in data['users'].values():UserProfileResponse.model_validate(user['profile'])
  assert data['users'] and data['devices'] and data['servers']
  print(json.dumps({'read_only':True,'build_sec':round(time.monotonic()-start,3),
   'users':len(data['users']),'devices':len(data['devices']),'grants':len(data['grants']),
   'bytes':len(json.dumps(data)),'servers':list(data['servers'])}))
asyncio.run(main())
'''
    if action=='cell':
        return PRELUDE+f'SLOT={slot!r}\nPROBE={PROBE!r}\nSHADOW={SHADOW!r}\n'+'''
async def main():
 async with AsyncSessionLocal() as db:
  await setting(db,'standby_agent_rollout_hold_until',str(time.time()+1800));await db.commit()
  nodes=await workers(db);node=next(n for n in nodes if slot_for_cell(n)==SLOT)
  password=resolve_ssh_password(node)
  ssh=_ssh_connect(node.public_ip,password,timeout=8)
  try:
   before=remote(ssh,PROBE)
   assert before['agent']=='active' and before['standby'] is False,'node must have a healthy Queen path'
   code,_,_=_run(ssh,"/opt/silent-vpn/cell-agent/venv/bin/pip install -q 'cryptography>=41' 'bcrypt>=4'",timeout=120)
   assert code==0,'recovery dependencies not installed'
   import base64
   backup='/opt/silent-vpn/cell-agent/.before-standby-'+str(int(time.time()))
   code,_,_=_run(ssh,'mkdir -m 700 '+backup+' && cp /opt/silent-vpn/cell-agent/*.py '+backup+'/',timeout=15)
   assert code==0,'backup failed'
   current=await db.get(AppSetting,'standby_offline_cells_v1')
   enabled=json.loads(current.value) if current else []
   try:
    try:
     upgrade_cell_agent_via_ssh(node.public_ip,password,link_capacity_mbps=float(node.link_capacity_mbps or 1000))
    except RuntimeError:
     # The legacy upgrader checks curl only two seconds after process start.
     # On a busy node imports/startup may take longer. Accept only the exact
     # live build's health response; otherwise the outer rollback still applies.
     deadline=time.monotonic()+25
     while True:
      code,out,_=_run(ssh,'curl --connect-timeout 1 --max-time 2 -sf http://127.0.0.1:9100/health',timeout=5)
      if code==0:
       try:healthy=json.loads(out)
       except ValueError:healthy={}
       if healthy.get('status')=='ok' and healthy.get('agent_build_id')==cell_agent_build_id():break
      if time.monotonic()>=deadline:raise
      time.sleep(1)
    from app.services.standby_snapshot import ENABLED_KEY
    if str(node.id) not in enabled:enabled.append(str(node.id))
    await setting(db,ENABLED_KEY,json.dumps(enabled));await db.commit()
    from app.services.hive_cell_sync import sync_cell_manifest_by_id
    assert await sync_cell_manifest_by_id(db,node.id),'manifest delivery failed'
    result=remote(ssh,SHADOW)
    after=remote(ssh,PROBE)
    assert after['wdtt']==before['wdtt'] and after['ifindex']==before['ifindex'],'VPN process/interface changed'
    assert after['standby'] is False and after['agent']=='active','control plane not healthy'
    assert after['agent_pid']!=before['agent_pid'],'new agent process did not start'
    assert after['nat']==before['nat'],'DNAT changed'
    changed=[p for p,v in before['peers'].items() if v['live'] and after['peers'].get(p,{}).get('allowed')!=v['allowed']]
    assert not changed,'live peer allowed-ips changed'
    result.update(wdtt_unchanged=True,live_peers_preserved=sum(v['live'] for v in before['peers'].values()),dnat_unchanged=True)
    print(json.dumps(result))
   except BaseException:
    await setting(db,'standby_offline_cells_v1',json.dumps([x for x in enabled if x!=str(node.id)]))
    await db.commit()
    _run(ssh,'cp '+backup+'/*.py /opt/silent-vpn/cell-agent/ && systemctl restart silent-cell-agent',timeout=25)
    raise
  finally:ssh.close()
asyncio.run(main())
'''
    if action=='accept':
        return PRELUDE+f'SHADOW={SHADOW!r}\nPROBE={PROBE!r}\n'+'''
import httpx,hashlib
from datetime import timedelta
from app.core.security import create_access_token
async def main():
 from app.services.standby_snapshot import build_common
 from app.services.hive_cell_sync import sync_cell_manifest_by_id
 async with AsyncSessionLocal() as db:
  await setting(db,'standby_agent_rollout_hold_until',str(time.time()+1800));await db.commit()
  common=await build_common(db)
  uid=next(uid for uid,u in common['users'].items() if u['vpn_allowed'] and not u['is_admin'])
  token=create_access_token(uid,timedelta(minutes=5))
  async with httpx.AsyncClient(timeout=5) as client:
   r=await client.get('http://127.0.0.1:8000/api/vpn/hashes',headers={'Authorization':'Bearer '+token})
   assert r.status_code==200,'legacy-shaped JWT rejected by main API'
  digest=hashlib.sha256(token.encode()).hexdigest()
  deadline=time.monotonic()+8
  while True:
   registered=await db.scalar(text('SELECT COUNT(*) FROM standby_token_grants WHERE token_hash=:hash'),{'hash':digest})
   if registered:break
   assert time.monotonic()<deadline,'verified token was not recorded'
   await asyncio.sleep(.2)
  results=[];nodes=await workers(db)
  for node in nodes:
   assert await sync_cell_manifest_by_id(db,node.id),'legacy grant snapshot not delivered'
   ssh=_ssh_connect(node.public_ip,resolve_ssh_password(node),timeout=8)
   try:
    try:result=remote(ssh,'LEGACY_TOKEN='+repr(token)+chr(10)+SHADOW)
    except RuntimeError as exc:raise RuntimeError('accept '+slot_for_cell(node)+': '+str(exc))
    result['clock_delta_sec']=round(result.pop('node_epoch')-time.time(),1)
    state=remote(ssh,PROBE)
    assert state['agent']=='active' and state['standby'] is False,'node control plane not healthy'
    result['wdtt']=state['wdtt'];results.append(result)
   finally:ssh.close()
  # Cover at least one complete sixty-second replication/cache renewal period.
  samples=[]
  async with httpx.AsyncClient(timeout=2) as client:
   end=time.monotonic()+70
   while time.monotonic()<end:
    start=time.monotonic();r=await client.get('http://127.0.0.1:8000/api/health')
    assert r.status_code==200,'health failed during snapshot rotation'
    samples.append(time.monotonic()-start);await asyncio.sleep(1)
  assert max(samples)<1.5,'API health latency exceeded safety bound'
  row=await db.execute(text('SELECT COUNT(*) FROM standby_token_grants WHERE expires_at>:now'),{'now':time.time()})
  print(json.dumps({'legacy_verified_digest_replicated':True,'cells':results,
    'health_samples':len(samples),'health_max_ms':round(max(samples)*1000,1),
    'health_mean_ms':round(sum(samples)/len(samples)*1000,1),'verified_legacy_grants':row.scalar_one()}))
asyncio.run(main())
'''
    if action=='disable':
        return PRELUDE+f'SLOT={slot!r}\n'+'''
async def main():
 async with AsyncSessionLocal() as db:
  from app.services.standby_snapshot import ENABLED_KEY,enabled_cells
  nodes=[n for n in await workers(db) if not SLOT or slot_for_cell(n)==SLOT]
  assert nodes,'unknown cell slot'
  remaining=await enabled_cells(db)
  remaining.difference_update(str(n.id) for n in nodes)
  await setting(db,ENABLED_KEY,json.dumps(sorted(remaining)));await db.commit()
  from app.services.hive_cell_sync import sync_cell_manifest_by_id
  delivered={slot_for_cell(n):await sync_cell_manifest_by_id(db,n.id) for n in nodes}
  print(json.dumps({'disabled':list(delivered),'manifest_delivered':delivered,'vpn_restarted':False}))
asyncio.run(main())
'''
    if action=='release':
        return PRELUDE+f'SHADOW={SHADOW!r}\n'+'''
async def main():
 async with AsyncSessionLocal() as db:
  from app.services.standby_snapshot import enabled_cells
  enabled=await enabled_cells(db);target=cell_agent_build_id();results=[]
  for node in await workers(db):
   assert str(node.id) in enabled,'not all cells enabled'
   ssh=_ssh_connect(node.public_ip,resolve_ssh_password(node),timeout=8)
   try:
    result=remote(ssh,SHADOW)
    code,out,_=_run(ssh,"cd /opt/silent-vpn/cell-agent && venv/bin/python -c 'from build_id import agent_build_id; print(agent_build_id())'")
    assert code==0 and out.strip()==target,'agent build mismatch'
    results.append(result)
   finally:ssh.close()
  await setting(db,'standby_agent_rollout_hold_until','0');await db.commit()
  print(json.dumps({'all_cells_ready':len(results),'build_id':target,'rollout_hold_released':True,'cells':results}))
asyncio.run(main())
'''
    raise ValueError(action)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','validate','cell','accept','release','disable'])
    parser.add_argument('--slot')
    parser.add_argument('--receipt',type=Path)
    args=parser.parse_args()
    if args.action=='cell' and not args.slot:parser.error('cell requires --slot')
    program=source_for(args.action,args.slot)
    compile(program,'rollout-remote','exec')
    ssh=connect(timeout=8,attempts=1)
    try:
        inp,out,err=ssh.exec_command(f'docker exec -i -e PYTHONPATH=/app {CONTAINER} python -',timeout=300)
        inp.write(program);inp.flush();inp.channel.shutdown_write()
        raw=out.read().decode();errors=err.read().decode()
        if out.channel.recv_exit_status():
            raise SystemExit(errors[-1600:] or 'remote rollout failed')
        data=json.loads(raw)
        if args.receipt:args.receipt.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(data,ensure_ascii=False))
    finally:ssh.close()


if __name__=='__main__':main()
