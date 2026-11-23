"""Exercise HTTP status while cell-agent is applying a manifest."""
import asyncio
import importlib.util
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'cell-agent'))
spec = importlib.util.spec_from_file_location('cell_control_fixture', ROOT / 'cell-agent/main.py')
agent = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = agent
spec.loader.exec_module(agent)


class CellControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_served_during_manifest_and_peer_updates_stay_serial(self):
        entered = threading.Event()
        release = threading.Event()
        effects = []

        def apply(payload):
            effects.append(('started', payload['version']))
            if payload['version'] == 1:
                entered.set()
                release.wait(1.5)
            effects.append(('finished', payload['version']))

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(agent, 'HIVE_MANIFEST_PATH', Path(directory) / 'manifest.json'), \
                patch.object(agent, 'CELL_AGENT_SECRET', 'fixture-cell-secret'), \
                patch.object(agent, 'on_manifest_updated', apply), \
                patch.object(agent, '_STATUS_CACHE', agent.StatusCache()), \
                patch.object(agent, '_collect_status', return_value={'cpu_percent': 37.0}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app),
                                         base_url='http://agent',
                                         headers={'X-Cell-Agent-Secret': agent.CELL_AGENT_SECRET}) as client:
                first = asyncio.create_task(client.post('/v1/sync-manifest', json={'version': 1}))
                second = None
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                    second = asyncio.create_task(client.post('/v1/sync-manifest', json={'version': 2}))
                    health, status = await asyncio.wait_for(
                        asyncio.gather(client.get('/health'), client.get('/v1/status')), timeout=0.5)
                    self.assertEqual(health.status_code, 200)
                    self.assertEqual(status.json(), {'cpu_percent': 37.0})
                    self.assertEqual(effects, [('started', 1)])
                    self.assertFalse(first.done())
                finally:
                    release.set()
                    responses = await asyncio.gather(first, *([second] if second is not None else []))
                self.assertEqual([response.json()['version'] for response in responses], [1, 2])
                self.assertEqual(effects, [('started', 1), ('finished', 1), ('started', 2), ('finished', 2)])


if __name__ == '__main__':
    unittest.main()
