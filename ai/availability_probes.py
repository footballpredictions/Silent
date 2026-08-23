"""Пробы доступности: локальные, с российских нод и со наших сот.

Все пробы только читают: ни одного действия, меняющего состояние сервера.
Любой отказ внешнего сервиса деградирует мягко — агент продолжает работать
на локальных пробах и клиентской телеметрии.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import time
from typing import Any, Iterable

import httpx

from ai.availability_model import (
    ERR_DNS,
    ERR_HTTP,
    ERR_NONE,
    ERR_OTHER,
    ERR_REFUSED,
    ERR_RESET,
    ERR_TIMEOUT,
    ERR_TLS,
    ERR_UNREACHABLE,
    NodeResult,
    ProbeResult,
)

logger = logging.getLogger(__name__)

CHECKHOST_BASE = "https://check-host.net"
CHECKHOST_HEADERS = {"Accept": "application/json", "User-Agent": "silent-availability-agent/1.0"}
_NODES_TTL_SEC = 6 * 3600

_nodes_cache: dict[str, Any] = {"ts": 0.0, "nodes": {}}


# ---------------------------------------------------------------- локальные пробы


def _os_error_kind(exc: BaseException) -> str:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ERR_TIMEOUT
    if isinstance(exc, ConnectionRefusedError):
        return ERR_REFUSED
    if isinstance(exc, ConnectionResetError):
        return ERR_RESET
    if isinstance(exc, socket.gaierror):
        return ERR_DNS
    if isinstance(exc, ssl.SSLError):
        return ERR_TLS
    if isinstance(exc, OSError):
        errno = getattr(exc, "errno", None)
        if errno in (
            getattr(socket, "EHOSTUNREACH", 113),
            getattr(socket, "ENETUNREACH", 101),
        ):
            return ERR_UNREACHABLE
        text = str(exc).lower()
        if "unreachable" in text or "no route" in text:
            return ERR_UNREACHABLE
        if "reset" in text:
            return ERR_RESET
        if "refused" in text:
            return ERR_REFUSED
        return ERR_OTHER
    return ERR_OTHER


async def tcp_probe(host: str, port: int, channel: str, timeout: float = 5.0) -> ProbeResult:
    started = time.monotonic()
    writer = None
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        return ProbeResult(
            channel=channel, ok=True, latency_ms=(time.monotonic() - started) * 1000
        )
    except BaseException as e:  # noqa: BLE001 — важна причина, а не тип
        return ProbeResult(
            channel=channel, ok=False, error_kind=_os_error_kind(e), detail=str(e)[:200]
        )
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def tls_probe(
    host: str,
    port: int,
    channel: str,
    *,
    server_name: str | None = None,
    timeout: float = 7.0,
) -> ProbeResult:
    """TLS-рукопожатие. server_name=None — без SNI (контроль для блокировки по имени)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    started = time.monotonic()
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=server_name or None),
            timeout,
        )
        return ProbeResult(
            channel=channel, ok=True, latency_ms=(time.monotonic() - started) * 1000
        )
    except BaseException as e:  # noqa: BLE001
        return ProbeResult(
            channel=channel, ok=False, error_kind=_os_error_kind(e), detail=str(e)[:200]
        )
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def http_probe(
    url: str, channel: str, *, timeout: float = 8.0, expect: str = ""
) -> ProbeResult:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=False) as c:
            resp = await c.get(url)
    except BaseException as e:  # noqa: BLE001
        return ProbeResult(
            channel=channel, ok=False, error_kind=_os_error_kind(e), detail=str(e)[:200]
        )
    latency = (time.monotonic() - started) * 1000
    body = resp.text[:200] if resp.content else ""
    if resp.status_code >= 400 or (expect and expect not in body):
        return ProbeResult(
            channel=channel,
            ok=False,
            latency_ms=latency,
            error_kind=ERR_HTTP,
            detail=f"HTTP {resp.status_code}: {body[:120]}",
        )
    return ProbeResult(channel=channel, ok=True, latency_ms=latency, detail=f"HTTP {resp.status_code}")


async def udp_listen_probe(host: str, port: int, channel: str, timeout: float = 2.0) -> ProbeResult:
    """UDP-порт: отказ виден только по ICMP unreachable, тишина ничего не доказывает.

    wdtt и WireGuard не отвечают на посторонний пакет, поэтому «нет ответа» —
    это inconclusive, а не «всё хорошо».
    """

    def _send() -> tuple[bool, str]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.send(b"\x00" * 16)
            try:
                sock.recv(256)
                return True, "ответ получен"
            except socket.timeout:
                return True, "нет ответа (норма для wdtt/WG)"
            except ConnectionRefusedError:
                return False, "ICMP port unreachable — порт не слушает"
        finally:
            sock.close()

    try:
        alive, detail = await asyncio.wait_for(asyncio.to_thread(_send), timeout + 2)
    except BaseException as e:  # noqa: BLE001
        return ProbeResult(
            channel=channel,
            ok=False,
            error_kind=_os_error_kind(e),
            detail=str(e)[:200],
            inconclusive=True,
        )
    if not alive:
        return ProbeResult(channel=channel, ok=False, error_kind=ERR_REFUSED, detail=detail)
    return ProbeResult(channel=channel, ok=True, detail=detail, inconclusive=True)


async def dns_probe(name: str, channel: str, timeout: float = 5.0) -> ProbeResult:
    def _resolve() -> tuple[str, ...]:
        infos = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)
        return tuple(sorted({i[4][0] for i in infos}))

    try:
        ips = await asyncio.wait_for(asyncio.to_thread(_resolve), timeout)
    except BaseException as e:  # noqa: BLE001
        return ProbeResult(
            channel=channel, ok=False, error_kind=_os_error_kind(e), detail=str(e)[:200]
        )
    return ProbeResult(channel=channel, ok=bool(ips), resolved_ips=ips, detail=", ".join(ips))


# --------------------------------------------------- внешние точки наблюдения (РФ)


def _checkhost_error_kind(text: str) -> str:
    low = (text or "").lower()
    if "timed out" in low or "timeout" in low:
        return ERR_TIMEOUT
    if "refused" in low:
        return ERR_REFUSED
    if "reset" in low:
        return ERR_RESET
    if "unreachable" in low or "no route" in low:
        return ERR_UNREACHABLE
    if "name or service" in low or "resolve" in low or "nxdomain" in low:
        return ERR_DNS
    if not low:
        return ERR_OTHER
    return ERR_OTHER


async def fetch_checkhost_nodes(timeout: float = 10.0) -> dict[str, dict[str, str]]:
    """Список нод внешнего сервиса с их страной и ASN (кешируется на 6 часов)."""
    now = time.time()
    if _nodes_cache["nodes"] and (now - float(_nodes_cache["ts"])) < _NODES_TTL_SEC:
        return dict(_nodes_cache["nodes"])
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=CHECKHOST_HEADERS) as c:
            resp = await c.get(f"{CHECKHOST_BASE}/nodes/hosts")
            resp.raise_for_status()
            raw = resp.json()
    except Exception as e:
        logger.warning("availability: список внешних нод недоступен: %s", e)
        return dict(_nodes_cache["nodes"])

    nodes: dict[str, dict[str, str]] = {}
    for name, info in (raw.get("nodes") or raw or {}).items():
        loc = (info or {}).get("location") or []
        asn = str((info or {}).get("asn") or "")
        nodes[str(name)] = {
            "country": str(loc[0] if len(loc) > 0 else "").lower(),
            "country_name": str(loc[1] if len(loc) > 1 else ""),
            "city": str(loc[2] if len(loc) > 2 else ""),
            "asn": asn,
            "ip": str((info or {}).get("ip") or ""),
        }
    if nodes:
        _nodes_cache["nodes"] = nodes
        _nodes_cache["ts"] = now
    return dict(nodes)


def pick_nodes(
    nodes: dict[str, dict[str, str]], *, ru_limit: int, world_limit: int
) -> tuple[list[str], list[str]]:
    ru = sorted(n for n, i in nodes.items() if i.get("country") == "ru")
    world = sorted(
        n for n, i in nodes.items() if i.get("country") in ("de", "nl", "fi", "pl", "us")
    )
    return ru[:ru_limit], world[:world_limit]


def _parse_node_payload(kind: str, payload: Any) -> tuple[bool, float | None, str, str, tuple[str, ...]]:
    """Единый разбор ответа внешнего сервиса → (ok, latency_ms, error_kind, detail, ips)."""
    if payload is None:
        return False, None, ERR_TIMEOUT, "нода не вернула результат", ()
    item = payload[0] if isinstance(payload, list) and payload else payload
    if item is None:
        return False, None, ERR_TIMEOUT, "нет ответа от ноды", ()

    if isinstance(item, dict):
        err = str(item.get("error") or "")
        if err:
            return False, None, _checkhost_error_kind(err), err[:180], ()
        if kind == "dns":
            ips = tuple(str(x) for x in (item.get("A") or []))
            if not ips:
                return False, None, ERR_DNS, "нет A-записей", ()
            return True, None, ERR_NONE, ", ".join(ips), ips
        seconds = item.get("time")
        address = str(item.get("address") or "")
        if seconds is None:
            return False, None, ERR_TIMEOUT, "нет времени соединения", ()
        return True, float(seconds) * 1000, ERR_NONE, address, ((address,) if address else ())

    if isinstance(item, list):
        if kind == "ping":
            oks = [a for a in item if isinstance(a, list) and a and str(a[0]).upper() == "OK"]
            if not oks:
                first = item[0] if item and isinstance(item[0], list) else []
                detail = str(first[0]) if first else "нет ответа"
                return False, None, _checkhost_error_kind(detail), detail[:180], ()
            times = [float(a[1]) * 1000 for a in oks if len(a) > 1 and a[1] is not None]
            best = min(times) if times else None
            return True, best, ERR_NONE, f"{len(oks)}/{len(item)} ответов", ()
        # http: [success, time, reason, code, ip]
        success = bool(item[0]) if item else False
        seconds = float(item[1]) if len(item) > 1 and item[1] is not None else None
        reason = str(item[2]) if len(item) > 2 else ""
        code = str(item[3]) if len(item) > 3 and item[3] is not None else ""
        if not success:
            return False, None, _checkhost_error_kind(reason), f"{reason} {code}".strip(), ()
        latency = seconds * 1000 if seconds is not None else None
        # 3xx — ответ от нашего nginx: TLS с нашим SNI дошёл, это не блокировка.
        if code and not (code.startswith("2") or code.startswith("3")):
            return False, latency, ERR_HTTP, f"HTTP {code} {reason}".strip(), ()
        return True, latency, ERR_NONE, f"HTTP {code}", ()

    return False, None, ERR_OTHER, str(item)[:120], ()


async def vantage_check(
    kind: str,
    host: str,
    nodes: Iterable[str],
    node_info: dict[str, dict[str, str]],
    *,
    poll_attempts: int = 5,
    poll_delay: float = 2.0,
    timeout: float = 12.0,
) -> dict[str, NodeResult]:
    """Запустить внешнюю проверку и дождаться результатов по указанным нодам."""
    node_list = [n for n in nodes if n]
    if not node_list:
        return {}
    params: list[tuple[str, str]] = [("host", host)] + [("node", n) for n in node_list]
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=CHECKHOST_HEADERS) as client:
            start = await client.get(f"{CHECKHOST_BASE}/check-{kind}", params=params)
            start.raise_for_status()
            started = start.json()
            request_id = str(started.get("request_id") or "")
            if not request_id:
                raise ValueError(f"нет request_id: {str(started)[:120]}")

            raw: dict[str, Any] = {}
            for attempt in range(poll_attempts):
                await asyncio.sleep(poll_delay if attempt else 1.0)
                res = await client.get(f"{CHECKHOST_BASE}/check-result/{request_id}")
                if res.status_code >= 400:
                    continue
                raw = res.json() or {}
                if raw and all(raw.get(n) is not None for n in node_list):
                    break
    except Exception as e:
        logger.warning("availability: внешняя проверка %s %s не удалась: %s", kind, host, e)
        return {}

    out: dict[str, NodeResult] = {}
    for node in node_list:
        info = node_info.get(node, {})
        ok, latency, error_kind, detail, ips = _parse_node_payload(kind, raw.get(node))
        out[node] = NodeResult(
            node=node,
            country=info.get("country", ""),
            city=info.get("city", ""),
            asn=info.get("asn", ""),
            ok=ok,
            latency_ms=latency,
            error_kind=error_kind,
            detail=detail,
            resolved_ips=ips,
        )
    return out


# ------------------------------------------------------------ пробы со наших сот


async def cell_net_probe(
    api_url: str,
    secret: str,
    targets: list[dict[str, Any]],
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Попросить cell-agent проверить цели со своей стороны (read-only)."""
    url = f"{api_url.rstrip('/')}/v1/net-probe"
    headers = {"X-Cell-Agent-Secret": secret}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        resp = await client.post(url, headers=headers, json={"targets": targets})
    if resp.status_code == 404:
        raise ValueError("cell-agent старой версии: /v1/net-probe отсутствует")
    if resp.status_code >= 400:
        raise ValueError(f"cell-agent HTTP {resp.status_code}: {resp.text[:160]}")
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("cell-agent: неверный ответ net-probe")
    return data
