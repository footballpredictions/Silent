"""Blocking SMTP fallback must never reuse another loop's pooled DB session."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import email_relays as relays
from app import database


class RelayLoopTests(unittest.TestCase):
    def setUp(self):
        self.engines = []

    def engine(self, *args, **kw):
        loop = asyncio.get_running_loop()
        owner = self
        class Engine:
            disposed = False
            async def dispose(self):
                owner.assertIs(asyncio.get_running_loop(), loop)
                self.disposed = True
        engine = Engine()
        self.engines.append(engine)
        return engine

    def session_factory(self, engine, **kw):
        loop = asyncio.get_running_loop()
        owner = self
        class Session:
            async def __aenter__(self):
                owner.assertIs(asyncio.get_running_loop(), loop)
                return self
            async def __aexit__(self, *args): pass
        return Session

    def exercise(self, in_loop):
        async def lookup(db): return [{'api_url': 'http://192.0.2.1:9100', 'secret': 'fixture'}]
        with patch.object(database, 'AsyncSessionLocal', side_effect=AssertionError('shared pool used from new loop')), \
             patch('sqlalchemy.ext.asyncio.create_async_engine', self.engine), \
             patch('sqlalchemy.ext.asyncio.async_sessionmaker', self.session_factory), \
             patch.object(relays, 'smtp_relays_from_db', lookup):
            async def inside(): return relays.load_smtp_relays_blocking()
            actual = asyncio.run(inside()) if in_loop else relays.load_smtp_relays_blocking()
        self.assertEqual(len(actual), 1, 'valid relays lost by cross-loop DB access')
        self.assertEqual(len(self.engines), 1)
        self.assertTrue(self.engines[0].disposed)

    def test_sync_background_sender(self): self.exercise(False)
    def test_sender_called_inside_running_loop(self): self.exercise(True)


if __name__ == '__main__': unittest.main()
