"""Read-only capacity/history/WG audit. Never print credentials, peer keys or device identities."""
from __future__ import annotations
import argparse
import json
import shlex
from pathlib import Path
from _deploy_common import CONTAINER, connect

PROGRAM = r'''
import asyncio,json,urllib.request,time,subprocess,uuid
from datetime import datetime,timedelta
from sqlalchemy import select,func
from app.database import AsyncSessionLocal
from app.models import HiveCell,HiveLoadSample
from app.models.admin_auth import AdminSession
from app.core.security import create_access_token
from app.config import settings

FIELDS=('online_count','cpu_percent','memory_percent','network_mbps','network_util_percent','link_capacity_mbps','cpu_cores','memory_total_gb','measurement_version')
LOAD_FIELDS=('cpu_percent','memory_percent','memory_total_gb','cpu_cores','network_mbps_rx','network_mbps_tx','network_util_percent','network_link_capacity_mbps','network_link_sysfs_mbps','wg_peers_total','wg_peers_never_hs','wg_peers_live_3m','wg_gc_last_removed','wdtt_active')
SETTINGS=('HIVE_CAPACITY_SAMPLE_INTERVAL_SEC','HIVE_CAPACITY_SAMPLE_RETENTION_HOURS','HIVE_CAPACITY_MAX_SAMPLES_PER_CELL','HIVE_CAPACITY_MIN_SAMPLES','HIVE_CAPACITY_MIN_ONLINE_FOR_LEARN','HIVE_CAPACITY_MIN_ONLINE_FOR_LIVE','HIVE_CAPACITY_LIVE_WEIGHT','HIVE_CAPACITY_PERCENTILE','HIVE_CAPACITY_PEAK_ACTIVE_SHARE','HIVE_CPU_PERCENT_THRESHOLD','HIVE_MEM_PERCENT_THRESHOLD','HIVE_BANDWIDTH_PERCENT_THRESHOLD','HIVE_WORKER_ROUTING_ENABLED','HIVE_REBALANCE_EXISTING_DEVICES')

async def snapshot():
    result={'at':datetime.utcnow().isoformat(),'settings':{k:getattr(settings,k) for k in SETTINGS},'cells':[]}
    async with AsyncSessionLocal() as db:
        session=(await db.execute(select(AdminSession).where(AdminSession.revoked_at.is_(None),AdminSession.expires_at>datetime.utcnow()).limit(1))).scalar_one_or_none()
        if not session: raise RuntimeError('No existing admin session; none created')
        token=create_access_token('admin',expires_delta=timedelta(minutes=5),jti=session.token_jti)
        request=urllib.request.Request('http://127.0.0.1:8000/api/admin/hive/cells',headers={'Authorization':'Bearer '+token,'Host':settings.ADMIN_PUBLIC_HOST})
        def fetch():
            with urllib.request.urlopen(request,timeout=30) as response: return json.load(response)
        cells=await asyncio.to_thread(fetch)
        for cell in cells:
            node=await db.get(HiveCell,uuid.UUID(cell['id']))
            query=select(HiveLoadSample).where(HiveLoadSample.cell_id==node.id,HiveLoadSample.sampled_at>=datetime.utcnow()-timedelta(hours=settings.HIVE_CAPACITY_SAMPLE_RETENTION_HOURS)).order_by(HiveLoadSample.sampled_at.desc()).limit(settings.HIVE_CAPACITY_MAX_SAMPLES_PER_CELL)
            if hasattr(HiveLoadSample,'measurement_version'):
                query=query.where(HiveLoadSample.measurement_version==2)
                versions=dict((await db.execute(select(HiveLoadSample.measurement_version,func.count(HiveLoadSample.id)).where(HiveLoadSample.cell_id==node.id).group_by(HiveLoadSample.measurement_version))).all())
            else: versions={}
            recent=list((await db.execute(query)).scalars().all())
            count=(await db.execute(select(func.count(HiveLoadSample.id)).where(HiveLoadSample.cell_id==node.id))).scalar_one()
            oldest=(await db.execute(select(func.min(HiveLoadSample.sampled_at)).where(HiveLoadSample.cell_id==node.id))).scalar_one()
            result['cells'].append({k:cell.get(k) for k in ('id','name','manual_slot_title','is_queen','status','online_count','online_count_db','assigned_devices','max_online','capacity')} | {'configured_max_clients':node.max_clients,'configured_link_mbps':node.link_capacity_mbps,'load':{k:(cell.get('load') or {}).get(k) for k in LOAD_FIELDS},'samples_total':count,'history_versions':versions,'oldest':oldest.isoformat() if oldest else None,'samples':[{k:getattr(row,k,1) for k in FIELDS}|{'sampled_at':row.sampled_at.isoformat()} for row in recent]})
        result['history_storage_bytes']=(await db.execute(select(func.pg_total_relation_size('hive_load_samples')))).scalar_one()
        from app.services.wg_peer_gc import known_device_pubs
        from app.services.vpn_kick import _queen_wg_dump
        known=await known_device_pubs(db)
        peers=await asyncio.to_thread(_queen_wg_dump)
        result['queen_wg_classification']={'total':len(peers),'known':sum(p.pub in known for p in peers),'never_known':sum(p.handshake_age is None and p.pub in known for p in peers),'never_extra':sum(p.handshake_age is None and p.pub not in known for p in peers),'stale_extra_6h':sum(p.handshake_age is not None and p.handshake_age>=21600 and p.pub not in known for p in peers)}
        from app.core.security import decrypt_value
        import paramiko
        nodes=list((await db.execute(select(HiveCell))).scalars().all())
        def runtime(node):
            if node.is_queen or not node.ssh_password_enc: return None
            client=paramiko.SSHClient();client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(node.public_ip,username='root',password=decrypt_value(node.ssh_password_enc),timeout=8,auth_timeout=8,banner_timeout=8,look_for_keys=False,allow_agent=False)
                # status reads current counters only: never call gc/kick/manifest application.
                code="""import sys,json,subprocess\nsys.path.insert(0,'/opt/silent-vpn/cell-agent')\nimport standby_runtime as runtime\nknown=runtime._known_device_pubs();peers=runtime._local_handshakes()\nresult={'total':len(peers),'known':sum(p in known for p,a in peers),'never_known':sum(a is None and p in known for p,a in peers),'never_extra':sum(a is None and p not in known for p,a in peers),'stale_extra_6h':sum(a is not None and a>=21600 and p not in known for p,a in peers)}\nresult['wdtt']=subprocess.run(['systemctl','show','wdtt.service','-p','MainPID','-p','ActiveState','-p','MemoryCurrent','-p','MemoryPeak'],capture_output=True,text=True).stdout\nprint(json.dumps(result))\n"""
                stdin,stdout,stderr=client.exec_command('/opt/silent-vpn/cell-agent/venv/bin/python -',timeout=20)
                stdin.write(code);stdin.flush();stdin.channel.shutdown_write()
                raw=stdout.read();status=stdout.channel.recv_exit_status()
                if status: return {'name':node.name,'error':'runtime read failed','exit':status}
                return {'name':node.name,**json.loads(raw)}
            except Exception as exc: return {'name':node.name,'error':type(exc).__name__}
            finally: client.close()
        result['workers_runtime']=[r for r in await asyncio.gather(*(asyncio.to_thread(runtime,n) for n in nodes)) if r]
    print(json.dumps(result),flush=True)
asyncio.run(snapshot())
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    client=connect(attempts=2)
    try:
        stdin,stdout,stderr=client.exec_command(f'docker exec -i {shlex.quote(CONTAINER)} python -',timeout=120)
        stdin.write(PROGRAM);stdin.flush();stdin.channel.shutdown_write()
        raw=stdout.read()
        code=stdout.channel.recv_exit_status()
        if code:
            print(stderr.read().decode(errors='replace')[-1500:])
            raise SystemExit(code)
        result=json.loads(raw)
        _,metrics,_=client.exec_command('systemctl show wdtt.service -p MainPID -p ActiveState -p MemoryCurrent -p MemoryPeak; free -m')
        result['queen_system']=metrics.read().decode()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'snapshot':str(args.output),'cells':[{'name':c['name'],'online':c['online_count'],'db_online':c['online_count_db'],'assigned':c['assigned_devices'],'limit':c['max_online'],'mode':c['capacity'].get('mode'),'wg':{k:v for k,v in c['load'].items() if k.startswith('wg_')},'history_total':c['samples_total'],'history_used':len(c['samples']),'oldest':c['oldest']} for c in result['cells']],'history_storage_bytes':result.get('history_storage_bytes'),'queen_wg_classification':result.get('queen_wg_classification'),'workers_runtime':result.get('workers_runtime'),'queen_system':result['queen_system']},ensure_ascii=False,indent=2))
    finally: client.close()

if __name__=='__main__': main()
