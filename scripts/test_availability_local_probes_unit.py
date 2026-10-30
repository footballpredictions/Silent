"""Keep local diagnostics independent of SSH/provisioning executor starvation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai import availability_probes as probes
from ai.availability_model import CHANNEL_API_HTTP, CHANNEL_DNS, ERR_TIMEOUT


class LocalProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_dns_is_not_timed_out_by_a_busy_shared_executor(self):
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        ready = asyncio.Event()
        release = threading.Event()
        def unrelated_ssh_work():
            loop.call_soon_threadsafe(ready.set)
            release.wait(3)
        busy = loop.run_in_executor(None, unrelated_ssh_work)
        await ready.wait()
        try:
            answer = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("198.51.100.1", 0))]
            with patch.object(probes.socket, "getaddrinfo", return_value=answer):
                result = await probes.dns_probe("api.example.test", CHANNEL_DNS, timeout=0.1)
            self.assertTrue(result.ok, (result.error_kind, result.detail))
            self.assertEqual(result.resolved_ips, ("198.51.100.1",))
        finally:
            release.set()
            await busy

    async def test_empty_httpx_timeout_is_identified_and_explained(self):
        def handle(request):
            raise httpx.ConnectTimeout("", request=request)
        real_client = httpx.AsyncClient
        with patch.object(probes.httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            result = await probes.http_probe("https://api.example.test/api/health", CHANNEL_API_HTTP)
        self.assertEqual(result.error_kind, ERR_TIMEOUT)
        self.assertIn("ConnectTimeout", result.detail)

    async def test_http_uses_known_target_when_shared_dns_executor_is_busy(self):
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        ready = asyncio.Event()
        release = threading.Event()
        received = []
        async def serve(reader, writer):
            received.append((await reader.readuntil(b"\r\n\r\n")).decode())
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(serve, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        def block():
            loop.call_soon_threadsafe(ready.set)
            release.wait(3)
        busy = loop.run_in_executor(None, block)
        await ready.wait()
        try:
            result = await probes.http_probe(f"http://api.example.test:{port}/api/health", CHANNEL_API_HTTP,
                                             connect_host="127.0.0.1", timeout=0.4)
            self.assertTrue(result.ok, (result.error_kind, result.detail))
            self.assertIn(f"Host: api.example.test:{port}\r\n", received[0])
        finally:
            release.set()
            await busy
            server.close()
            await server.wait_closed()

    async def test_pinned_https_preserves_domain_sni_and_host(self):
        seen = []
        def handle(request):
            seen.append(request)
            return httpx.Response(200, text="ok")
        real_client = httpx.AsyncClient
        with patch.object(probes.httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            result = await probes.http_probe("https://api.example.test:8443/api/health", CHANNEL_API_HTTP,
                                             connect_host="198.51.100.1")
        self.assertTrue(result.ok)
        self.assertEqual(seen[0].url.host, "198.51.100.1")
        self.assertEqual(seen[0].headers["host"], "api.example.test:8443")
        self.assertEqual(seen[0].extensions["sni_hostname"], "api.example.test")

    async def test_http_cancellation_does_not_become_a_failed_measurement(self):
        entered = asyncio.Event()
        async def handle(request):
            entered.set()
            await asyncio.Event().wait()
        real_client = httpx.AsyncClient
        with patch.object(probes.httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
            task = asyncio.create_task(probes.http_probe("https://api.example.test/api/health", CHANNEL_API_HTTP))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task


if __name__ == "__main__":
    unittest.main()
