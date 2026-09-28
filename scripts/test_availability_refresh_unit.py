"""Регрессии: пятая нода, занятый executor и пробы после provision."""
from __future__ import annotations

import ast
import asyncio
import socket
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy.orm import declarative_base
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None, Base=declarative_base()))

from ai import availability_agent as agent
from ai.availability_model import CHANNEL_WDTT_UDP, NodeResult, TargetSnapshot
from ai.availability_probes import udp_listen_probe


async def test_all_cells_receive_external_probes():
    # Улей + четыре соты; далее подключается пятая. Пробы нужны всем.
    for count in (4, 5, 8):
        targets = [TargetSnapshot(name="Улей", host="127.0.0.1", role="queen", domain="queen.test")]
        targets += [TargetSnapshot(name=f"Сота {i}", host=f"127.0.0.{i+1}", role="cell", agent_port=8090) for i in range(1, count+1)]
        calls = []

        async def vantage(kind, host, nodes, info):
            calls.append((kind, host))
            return {n: NodeResult(node=n, country=info[n]["country"], ok=True) for n in nodes}

        warnings = []
        with patch.object(agent.settings, "AVAILABILITY_MAX_EXTERNAL_TARGETS", 0), patch.object(agent.settings, "AVAILABILITY_MAX_EXTERNAL_CHECKS", 12), patch.object(agent, "fetch_checkhost_nodes", AsyncMock(return_value={"ru": {"country": "ru"}, "de": {"country": "de"}})), patch.object(agent, "pick_nodes", return_value=(["ru"], ["de"])), patch.object(agent, "vantage_check", vantage):
            await agent._run_external_probes(targets, ru_limit=1, world_limit=1, warnings=warnings)
        assert all(t.ru and t.world for t in targets), f"нет проб: {[t.name for t in targets if not t.ru]}"
        assert all("agent_tcp" in t.ru for t in targets[1:]), "новым сотам нужен TCP, не только ping"


async def test_external_probes_overlap_and_explain_missing_nodes():
    targets = [TargetSnapshot(name="Улей", host="127.0.0.1", role="queen", domain="queen.test")]
    targets += [TargetSnapshot(name=f"Сота {i}", host=f"127.0.0.{i+1}", role="cell", agent_port=8090) for i in range(1,5)]
    active = peak = 0
    async def vantage(kind, host, nodes, info):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.015)
        active -= 1
        return {"ru1":NodeResult(node="ru1", country="ru", ok=True),
                "ru2":NodeResult(node="ru2", country="ru", ok=False, error_kind="pending")}
    warnings = []
    with patch.object(agent.settings,"AVAILABILITY_MAX_EXTERNAL_TARGETS",0), patch.object(agent.settings,"AVAILABILITY_MAX_EXTERNAL_CHECKS",12), patch.object(agent,"fetch_checkhost_nodes",AsyncMock(return_value={"ru1":{"country":"ru"},"ru2":{"country":"ru"}})), patch.object(agent,"pick_nodes",return_value=(["ru1","ru2"],[])), patch.object(agent,"vantage_check",vantage):
        meta = await agent._run_external_probes(targets,ru_limit=6,world_limit=0,warnings=warnings)
    assert 1 < peak <= 3, f"probes still serial or unlimited: peak={peak}"
    assert any("ru2" in w for w in warnings), "silent loss of a probe node"
    assert any("6" in w and "2" in w for w in warnings), "requested/available count unexplained"
    assert "tls_no_sni" in targets[0].ru, "missing HTTPS IP control"
    assert meta["checks"] == 13  # Five public TCP endpoints + pings + three HTTPS/DNS controls.


async def test_udp_silence_with_busy_executor():
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
    entered, release = threading.Event(), threading.Event()
    def block():
        entered.set()
        release.wait(5)
    blocking = loop.run_in_executor(None, block)
    while not entered.is_set():
        await asyncio.sleep(0)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    try:
        result = await udp_listen_probe("127.0.0.1", sock.getsockname()[1], CHANNEL_WDTT_UDP, timeout=0.03)
        assert result.ok and result.inconclusive and not result.error_kind, result.to_dict()
    finally:
        sock.close()
        release.set()
        await blocking


async def test_udp_cancellation_propagates():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    try:
        task = asyncio.create_task(udp_listen_probe("127.0.0.1", sock.getsockname()[1], CHANNEL_WDTT_UDP, timeout=1))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("отмена превратилась в ошибку порта")
    finally:
        sock.close()


async def test_udp_response_is_conclusive():
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("127.0.0.1", 0))
    async def reply():
        _, sender = await loop.sock_recvfrom(sock, 256)
        await loop.sock_sendto(sock, b"ok", sender)
    responder = asyncio.create_task(reply())
    try:
        result = await udp_listen_probe("127.0.0.1", sock.getsockname()[1], CHANNEL_WDTT_UDP, timeout=1)
        assert result.ok and not result.inconclusive, result.to_dict()
        await responder
    finally:
        responder.cancel()
        sock.close()


async def test_udp_closed_port_is_an_error():
    if sys.platform == "win32":
        return  # Windows отдаёт иной ICMP-код; сервер работает на Linux.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    result = await udp_listen_probe("127.0.0.1", port, CHANNEL_WDTT_UDP, timeout=0.1)
    assert not result.ok and not result.inconclusive and result.error_kind == "refused", result.to_dict()


async def test_refresh_survives_workers_and_new_requests():
    from app.models import AppSetting
    from app.services import availability_store as store
    engine = create_engine("sqlite:///:memory:")
    AppSetting.__table__.create(engine)
    class DB:
        async def __aenter__(self):
            self.session = Session(engine)
            return self
        async def __aexit__(self, *args): self.session.close()
        async def execute(self, *args): return self.session.execute(*args)
        async def commit(self): self.session.commit()
    try:
        with patch.object(store, "AsyncSessionLocal", DB):
            old = await store.request_refresh()
            assert await store.pending_refresh() == old
            new = await store.request_refresh()
            await store.finish_refresh(old)
            assert await store.pending_refresh() == new, "старая проверка стерла новую соту"
            await store.finish_refresh(new)
            assert await store.pending_refresh() is None
    finally:
        engine.dispose()


async def test_pending_refresh_wakes_periodic_loop():
    with patch.object(agent.store, "pending_refresh", AsyncMock(return_value="new-cell")):
        await asyncio.wait_for(agent._wait_for_next_check(1800), timeout=0.1)


async def test_provision_queues_probes_after_commit():
    # Реальная функция API; только инфраструктура SSH/БД заменена адаптерами.
    tree = ast.parse((ROOT / "app/api/hive.py").read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_provision_cell_background")
    events = []
    cell = SimpleNamespace(status="provisioning", name="Сота 5", link_capacity_mbps=100)
    class DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def commit(self): events.append("commit:" + cell.status)
    async def request():
        assert events[-1] == "commit:active", events
        events.append("probes")
        # Проверки не должны превратить уже подключенную соту в error.
        raise RuntimeError("проверки временно недоступны")
    result = dict(public_ip="127.0.0.2", wg_public_key="key", api_url="http://127.0.0.2:8090")
    namespace = dict(asyncio=asyncio, uuid=SimpleNamespace(UUID=object), datetime=datetime,
        AsyncSessionLocal=DB, settings=agent.settings,
        hive_service=SimpleNamespace(get_cell_by_id=AsyncMock(return_value=cell)),
        hive_provision_service=SimpleNamespace(provision_cell_via_ssh=lambda *a, **kw: result),
        logger=SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, exception=lambda *a: None),
        push_incident=lambda **kw: None)
    from app.services import availability_store
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "hive.py", "exec"), namespace)
    with patch.object(availability_store, "request_refresh", request, create=True):
        await namespace[fn.name]("id", "127.0.0.2", "pwd", "secret", "https://queen.test", "wdtt")
    assert events == ["commit:active", "probes"], events
    assert cell.status == "active"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            try:
                asyncio.run(fn())
                print(f"ok {name}")
            except AssertionError as exc:
                print(f"FAIL {name}: {exc}")
                failed += 1
    raise SystemExit(bool(failed))
