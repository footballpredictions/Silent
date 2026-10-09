"""Capacity estimates must match the observed aggregate load and current hardware."""
from __future__ import annotations
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import hive_capacity as cap
from app.services import hive_service, wg_peer_gc
from app.models import HiveCell, HiveLoadSample


def sample(n=20, cpu=30, mem=40, net=21, cores=4, ram=8, link=1000):
    return NS(online_count=n, cpu_percent=cpu, memory_percent=mem, network_mbps=net,
              network_util_percent=net/link*100, cpu_cores=cores, memory_total_gb=ram, link_capacity_mbps=link)


def history(link=1000):
    return [sample(n=0,cpu=10,mem=20,net=1,link=link) for _ in range(3)] + [sample(link=link) for _ in range(10)]


async def profile(*, queen=True, link=1000, online=1, samples=None, current_cpu=30):
    cell=NS(id='test-node',is_queen=queen,name='Сота 2',link_capacity_mbps=link,max_clients=0)
    async def recent(db, cell_id): return samples if samples is not None else history(link)
    load=dict(cpu_percent=current_cpu,memory_percent=40,network_mbps_rx=21,network_mbps_tx=0,cpu_cores=4,memory_total_gb=8,network_link_capacity_mbps=link,wg_peers_live_3m=online)
    with patch.object(cap,'fetch_recent_samples',recent):
        return await cap.get_capacity_profile(None,cell,load=load,online_count=online)


async def test_observed_load_not_discounted_twice():
    actual=await profile(online=1)
    # Existing 20 online add 20 CPU points to the 10-point baseline: 1 point/online.
    assert actual.max_online <= 70, f'10 background + {actual.max_online}*1 observed CPU > threshold 80'


async def test_cpu_bound_workers_do_not_get_second_network_penalty():
    one=await profile(queen=False,link=1000)
    ten=await profile(queen=False,link=10000)
    assert one.max_online==ten.max_online, f'same CPU/RAM and ample network: {one.max_online} vs {ten.max_online}'


async def test_live_baseline_ignores_replaced_hardware():
    old=[sample(n=0,cpu=60,mem=70,net=1,cores=1,ram=1) for _ in range(30)]
    actual=await profile(online=20,samples=history()+old)
    assert actual.baseline_cpu==10 and actual.baseline_mem==20, f'old hardware leaked into live baseline: {actual.baseline_cpu}/{actual.baseline_mem}'


async def test_reported_limit_matches_component_limits():
    actual=await profile(online=20,samples=history(),current_cpu=50)
    limits=[v for v in (actual.limit_cpu,actual.limit_mem,actual.limit_network) if v is not None]
    assert actual.max_online==min(limits), f'overall={actual.max_online}, component limits={limits}'


async def test_sampler_uses_visible_node_online():
    worker=NS(id='worker',is_queen=False)
    queen=NS(id='queen',is_queen=True,link_capacity_mbps=None)
    class Rows:
        def scalars(self): return self
        def all(self): return [worker]
    class Db:
        async def execute(self, query): return Rows()
    async def ensure(db): return queen
    async def online(db, cell_id): return 1
    async def load(cell): return {'wg_peers_live_3m':30,'cpu_percent':30,'memory_percent':18,'cpu_cores':4,'memory_total_gb':8}
    recorded=[]
    async def record(db, cell_id, count, load, *, cell): recorded.append(count)
    with patch.object(hive_service,'ensure_queen_cell',ensure), patch.object(hive_service,'count_online_on_cell',online), patch.object(hive_service,'fetch_worker_cell_load',load), patch.object(cap,'queen_accepting_new_vpn',return_value=(True,{})), patch.object(wg_peer_gc,'queen_wg_peer_counts',return_value={'wg_peers_live_3m':0}), patch.object(cap,'record_sample',record):
        await cap.sample_all_cells(Db())
    assert recorded==[30], f'card shows 30 WG live but history recorded {recorded}'


async def test_active_only_history_is_not_background():
    actual=await profile(online=20,samples=[sample() for _ in range(10)])
    assert actual.baseline_cpu==0 and actual.baseline_mem==0, f'active VPN mistaken for background: {actual.baseline_cpu}/{actual.baseline_mem}'


async def test_manual_cap_and_real_overload_remain_honest():
    cell=NS(id='test',is_queen=True,link_capacity_mbps=1000,max_clients=5)
    async def recent(db, cell_id): return []
    load={'cpu_percent':95,'memory_percent':95,'cpu_cores':4,'memory_total_gb':8,'wg_peers_live_3m':30}
    with patch.object(cap,'fetch_recent_samples',recent):
        actual=await cap.get_capacity_profile(None,cell,load=load,online_count=1)
    assert actual.max_online<=5 and actual.max_online<30, 'must not disguise manual cap/overload by clamping to current online'
    assert actual.mode=='manual_cap' and actual.bottleneck=='manual_cap'


async def test_real_history_query_separates_versions_and_records_wg():
    engine=create_engine('sqlite://')
    HiveCell.__table__.create(engine)
    HiveLoadSample.__table__.create(engine)
    with Session(engine) as session:
        cell=HiveCell(id=uuid.uuid4(),name='test',is_queen=True,public_ip='192.0.2.1')
        session.add(cell);session.commit()
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(HiveLoadSample(cell_id=cell.id,sampled_at=now,online_count=1,cpu_percent=80,measurement_version=1))
        session.add(HiveLoadSample(cell_id=cell.id,sampled_at=now-timedelta(days=8),online_count=30,measurement_version=2))
        session.commit()
        class Db:
            def add(self, row): session.add(row)
            async def commit(self): session.commit()
            async def execute(self, query): return session.execute(query)
        db=Db()
        load={'cpu_percent':30,'memory_percent':18,'cpu_cores':4,'memory_total_gb':8,'wg_peers_live_3m':30}
        await cap.record_sample(db,cell.id,1,load,cell=cell)
        rows=await cap.fetch_recent_samples(db,cell.id)
        assert len(rows)==1 and rows[0].online_count==30 and rows[0].measurement_version==2, 'legacy history leaked in / new sample retained DB-only count'
        legacy=session.execute(text('select count(*) from hive_load_samples where measurement_version=1')).scalar_one()
        assert legacy==1, 'history should be separated, not deleted'
    engine.dispose()


async def test_queen_missing_wg_in_load_uses_real_snapshot():
    cell=NS(id='queen',is_queen=True,link_capacity_mbps=None,max_clients=0)
    async def recent(db, cell_id): return []
    load={'cpu_percent':30,'memory_percent':18,'cpu_cores':4,'memory_total_gb':8}
    with patch.object(cap,'fetch_recent_samples',recent), patch.object(wg_peer_gc,'queen_wg_peer_counts',return_value={'wg_peers_live_3m':30}):
        actual=await cap.get_capacity_profile(None,cell,load=load,online_count=1)
    assert actual.online_count_used==30 and actual.mode=='live' and actual.max_online>=30


async def test_network_limit_is_applied_once_and_monotonic():
    values=[]
    for link in (100,1000,10000):
        rows=[sample(n=0,cpu=10,mem=20,net=0,link=link) for _ in range(3)]+[sample(cpu=12,mem=21,net=200,link=link) for _ in range(10)]
        p=await profile(queen=False,link=link,samples=rows)
        values.append(p.max_online)
        assert p.max_online==min(p.limit_cpu,p.limit_mem,p.limit_network)
    assert values[0]==9 and values[1]==90 and values[2]>values[1], values


async def main():
    failures=0
    with patch.object(cap.settings,'HIVE_CPU_PERCENT_THRESHOLD',80), patch.object(cap.settings,'HIVE_MEM_PERCENT_THRESHOLD',85), patch.object(cap.settings,'HIVE_BANDWIDTH_PERCENT_THRESHOLD',90), patch.object(cap.settings,'HIVE_CAPACITY_PEAK_ACTIVE_SHARE',0.1):
        for test in (test_sampler_uses_visible_node_online,test_observed_load_not_discounted_twice,test_cpu_bound_workers_do_not_get_second_network_penalty,test_live_baseline_ignores_replaced_hardware,test_reported_limit_matches_component_limits,test_active_only_history_is_not_background,test_manual_cap_and_real_overload_remain_honest,test_real_history_query_separates_versions_and_records_wg,test_queen_missing_wg_in_load_uses_real_snapshot,test_network_limit_is_applied_once_and_monotonic):
            try:
                await test()
                print('PASS',test.__name__)
            except AssertionError as exc:
                failures+=1
                print('FAIL',test.__name__,str(exc))
    return failures


if __name__=='__main__':
    raise SystemExit(bool(asyncio.run(main())))
