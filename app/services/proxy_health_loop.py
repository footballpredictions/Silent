"""Фоновый health прокси-флота: probe + ротация SOCKS-порта при недоступности."""
from __future__ import annotations

import asyncio
import logging
import socket
from collections import defaultdict
from datetime import datetime

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# node_id -> consecutive external TCP failures
_fail_streak: dict[str, int] = defaultdict(int)


def _tcp_ok(host: str, port: int, timeout: float = 4.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


async def _rotate_via_agent(node, secret: str) -> dict | None:
    url = (node.agent_url or "").rstrip("/")
    if not url:
        return None
    timeout = settings.PROXY_AGENT_HTTP_TIMEOUT_SEC
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{url}/v1/rotate-port",
            headers={"X-Proxy-Agent-Secret": secret},
            json={},
        )
        r.raise_for_status()
        return r.json()


async def proxy_health_cycle() -> None:
    from app.database import AsyncSessionLocal
    from app.services import proxy_service

    async with AsyncSessionLocal() as db:
        nodes = await proxy_service.list_nodes(db)
        for node in nodes:
            if node.status in ("provisioning", "pending", "draining"):
                continue
            if not node.public_ip or not node.agent_url:
                continue
            nid = str(node.id)
            try:
                data = await proxy_service.probe_agent(node)
                agent_ok = (data or {}).get("status") in ("ok", "degraded")
            except Exception as e:
                agent_ok = False
                logger.warning("proxy health agent fail %s %s: %s", node.name, node.public_ip, e)

            tcp_ok = _tcp_ok(node.public_ip, int(node.socks_port))

            if agent_ok and tcp_ok:
                _fail_streak[nid] = 0
                if node.status in ("degraded", "error", "blocked", "active"):
                    await proxy_service.mark_seen(db, node, ok=True)
                continue

            _fail_streak[nid] += 1
            streak = _fail_streak[nid]
            reason = []
            if not agent_ok:
                reason.append("agent unreachable")
            if not tcp_ok:
                reason.append(f"tcp {node.public_ip}:{node.socks_port} closed/blocked")
            err = "; ".join(reason) or "health fail"
            await proxy_service.mark_seen(db, node, ok=False, error=err)
            logger.warning("proxy health %s streak=%s: %s", node.name, streak, err)

            threshold = max(1, int(settings.PROXY_HEALTH_FAIL_THRESHOLD))
            if streak < threshold:
                continue
            if not agent_ok:
                # без агента порт не сменить — blocked
                node.status = "blocked"
                node.last_error = (err + " → blocked (no agent for rotate)")[:2000]
                node.last_seen_at = datetime.utcnow()
                await db.commit()
                continue

            # Ротация порта через агент
            try:
                secret = proxy_service.agent_secret(node)
                result = await _rotate_via_agent(node, secret)
                if not result or not result.get("ok"):
                    raise RuntimeError(f"rotate failed: {result}")
                new_port = int(result.get("port") or 0)
                if new_port:
                    node.socks_port = new_port
                node.status = "active"
                node.last_error = (
                    f"port rotated {result.get('old_port')}→{new_port} after health fail"
                )[:2000]
                node.last_seen_at = datetime.utcnow()
                await db.commit()
                _fail_streak[nid] = 0
                logger.info(
                    "proxy %s rotated port %s→%s",
                    node.name,
                    result.get("old_port"),
                    new_port,
                )
            except Exception as e:
                node.status = "blocked"
                node.last_error = f"rotate failed: {e}"[:2000]
                await db.commit()
                logger.warning("proxy rotate failed %s: %s", node.name, e)


async def proxy_health_loop() -> None:
    interval = max(15, int(settings.PROXY_HEALTH_INTERVAL_SEC))
    await asyncio.sleep(20)
    logger.info("Proxy health loop started (every %ss)", interval)
    while True:
        try:
            await proxy_health_cycle()
        except Exception as e:
            logger.warning("Proxy health cycle failed: %s", e)
        await asyncio.sleep(interval)


def start_proxy_health_loop() -> asyncio.Task:
    return asyncio.create_task(proxy_health_loop())
