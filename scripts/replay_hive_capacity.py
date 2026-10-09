"""Replay a redacted production audit with the current model; no network or mutations."""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services import hive_capacity, hive_service


async def replay(snapshot):
    nodes=snapshot['cells']
    queen=next((n for n in nodes if n['is_queen']),None)
    def node(row):
        return SimpleNamespace(id=row['id'],name=row['name'],is_queen=row['is_queen'],link_capacity_mbps=row['configured_link_mbps'],max_clients=row['configured_max_clients'])
    async def recent(db, cell_id):
        row=next(r for r in nodes if r['id']==cell_id)
        return [SimpleNamespace(**s) for s in row['samples'] if s.get('measurement_version',1)==hive_capacity.MEASUREMENT_VERSION]
    async def get_queen(db): return node(queen) if queen else None
    output=[]
    with patch.object(hive_capacity,'fetch_recent_samples',recent), patch.object(hive_service,'get_queen_cell',get_queen), patch.object(hive_capacity,'queen_accepting_new_vpn',return_value=(True,queen['load'] if queen else {})):
        for row in nodes:
            p=await hive_capacity.get_capacity_profile(None,node(row),load=row['load'],online_count=row['online_count_db'])
            limits=[p.limit_cpu,p.limit_mem,p.limit_network]
            if all(v is not None for v in limits) and p.mode!='manual_cap':
                assert p.max_online==min(limits),(row['name'],p.to_dict())
            assert p.online_count_used==row['online_count'],(row['name'],p.online_count_used,row['online_count'])
            load=row['load']
            healthy=all(load.get(field) is not None and load[field]<snapshot['settings'][threshold] for field,threshold in [('cpu_percent','HIVE_CPU_PERCENT_THRESHOLD'),('memory_percent','HIVE_MEM_PERCENT_THRESHOLD'),('network_util_percent','HIVE_BANDWIDTH_PERCENT_THRESHOLD')])
            if healthy and not row['configured_max_clients']:
                assert p.max_online>=row['online_count'],(row['name'],row['online_count'],p.to_dict())
            output.append({'name':row['name'],'online':row['online_count'],'old_limit':row['max_online'],'replayed_limit':p.max_online,'mode':p.mode,'components':limits,'samples':p.samples_count})
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot',type=Path)
    args=parser.parse_args()
    snapshot=json.loads(args.snapshot.read_text(encoding='utf-8'))
    with patch.multiple(hive_capacity.settings,**snapshot['settings']):
        result=asyncio.run(replay(snapshot))
    print(json.dumps({'PASS':'all nodes, source parity, component limits, healthy headroom','nodes':result},ensure_ascii=True))
