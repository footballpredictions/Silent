"""Disk metrics across the real cell collector, load adapter and dashboard mapping."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'cell-agent')]
import httpx
import psutil
from app.services import hive_service
from app.services.dashboard_node_stats import _system_from_cell_load

spec=importlib.util.spec_from_file_location('cell_disk_collector',ROOT/'cell-agent/main.py')
agent=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=agent
spec.loader.exec_module(agent)


class CellDiskTests(unittest.IsolatedAsyncioTestCase):
    def collect(self, disk_error=False):
        disk=SimpleNamespace(total=100*1024**3,used=25*1024**3,percent=25.0)
        with patch('subprocess.run',return_value=SimpleNamespace(stdout='active',stderr='',returncode=0)), \
             patch.object(psutil,'cpu_percent',return_value=15.0), \
             patch.object(psutil,'virtual_memory',return_value=SimpleNamespace(percent=40,total=8*1024**3)), \
             patch.object(psutil,'disk_usage',side_effect=OSError('fixture inaccessible') if disk_error else None,return_value=disk), \
             patch.object(agent,'_network_status',return_value=('eth0',1.,2.,.2,1000.,None)), \
             patch.object(agent,'_memory_total_gb',return_value=8.), \
             patch.object(agent,'_cpu_model',return_value='Fixture CPU'), \
             patch.object(agent,'WG_SERVER_PUBLIC_KEY','fixture-key'):
            return agent._collect_status()

    async def adapt(self,payload):
        cell=SimpleNamespace(is_queen=False,status='active',api_url='http://93.184.216.34:9100',
                             api_secret_enc='fixture',link_capacity_mbps=1000,name='fixture',public_ip='93.184.216.34')
        original=httpx.AsyncClient
        transport=httpx.MockTransport(lambda request:httpx.Response(200,json=payload))
        with patch.object(hive_service,'decrypt_value',return_value='fixture'), \
             patch.object(hive_service.httpx,'AsyncClient',side_effect=lambda **kwargs:original(transport=transport,**kwargs)):
            return await hive_service.fetch_worker_cell_load(cell,report_incident=False)

    async def test_collected_disk_survives_all_three_layers(self):
        status=self.collect()
        self.assertEqual(status.get('disk_total_gb'),100.)
        load=await self.adapt(status)
        dashboard=_system_from_cell_load('fixture-node',load)
        for name,value in [('disk_total_gb',100.),('disk_used_gb',25.),('disk_percent',25.)]:
            self.assertEqual(load.get(name),value,name)
            self.assertEqual(dashboard[name],value,name)

    async def test_load_adapter_preserves_disk_even_for_zero_usage(self):
        load=await self.adapt({'cpu_percent':15.,'disk_total_gb':40.,'disk_used_gb':0.,'disk_percent':0.})
        self.assertEqual(load.get('disk_total_gb'),40.)
        self.assertEqual(load.get('disk_used_gb'),0.)
        self.assertEqual(load.get('disk_percent'),0.)

    def test_dashboard_does_not_discard_cell_disk(self):
        system=_system_from_cell_load('fixture-node',{'disk_total_gb':80.,'disk_used_gb':19.,'disk_percent':23.8})
        self.assertEqual(system['disk_total_gb'],80.)
        self.assertEqual(system['disk_used_gb'],19.)
        self.assertEqual(system['disk_percent'],23.8)

    async def test_legacy_agent_without_disk_stays_compatible(self):
        load=await self.adapt({'cpu_percent':15.,'memory_percent':50.,'memory_total_gb':8.})
        self.assertIsNotNone(load)
        system=_system_from_cell_load('fixture-node',load)
        self.assertEqual(system['memory_used_gb'],4.)
        self.assertIsNone(system['disk_percent'])
        self.assertIsNone(system['disk_total_gb'])

    async def test_disk_failure_does_not_hide_cpu_or_memory(self):
        status=self.collect(disk_error=True)
        self.assertIsNone(status.get('disk_percent'))
        self.assertEqual(status['cpu_percent'],15.)
        load=await self.adapt(status)
        self.assertIsNotNone(load)
        self.assertEqual(load['memory_total_gb'],8.)

    async def test_invalid_optional_disk_does_not_break_node_status(self):
        for value in ['unavailable',float('nan'),float('inf'),-1]:
            load=await self.adapt({'cpu_percent':15.,'disk_total_gb':value,'disk_used_gb':value,'disk_percent':value})
            self.assertIsNotNone(load)
            self.assertEqual(load['cpu_percent'],15.)
            self.assertIsNone(load.get('disk_percent'))


if __name__=='__main__':unittest.main()
