"""Standby на соте: WG peers из manifest, API :8000 при падении Улья."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HIVE_MANIFEST_PATH = Path("/etc/wdtt/hive_manifest.json")
HIVE_THEME_PATH = Path("/etc/wdtt/hive_theme.json")
HIVE_META_PATH = Path("/etc/wdtt/hive.json")
STANDBY_STATE_PATH = Path("/etc/wdtt/standby_mode.json")
WG_INTERFACE = (os.environ.get("WG_INTERFACE") or "wdtt0").strip()
INTERNAL_API_SECRET = (os.environ.get("INTERNAL_API_SECRET") or "").strip()
HIVE_API_URL = (os.environ.get("HIVE_API_URL") or "").strip().rstrip("/")
HIVE_QUEEN_IP = (os.environ.get("HIVE_QUEEN_IP") or "").strip()
STANDBY_API_PORT = int(os.environ.get("STANDBY_API_PORT") or "8000")
TUNNEL_GATEWAY = "10.66.66.1"

_standby_server_thread: threading.Thread | None = None
_last_peer_sync_version: int = -1
_queen_healthy: bool = True
_queen_fail_streak: int = 0
# 3 × 15с ≈ 45с. Один таймаут / рестарт api на Улье не должен переключать DNAT.
QUEEN_FAIL_BEFORE_STANDBY = 3
STALE_EXTRA_HS_SEC = 6 * 3600.0
NEVER_HS_GC_GRACE_SEC = 90.0
GC_EVERY_SEC = 90.0
GC_LIMIT = 40
_pending_never_hs: dict[str, float] = {}
_last_gc_at = 0.0
_wg_counts: dict[str, int] = {"total": 0, "never_hs": 0, "live_3m": 0, "last_removed": 0}


class InternalOnlineRequest(BaseModel):
    device_id: str
    online: bool = True


class InternalOnlineResponse(BaseModel):
    ok: bool
    subscription_active: bool = True
    vpn_allowed: bool = True


def _load_manifest() -> dict | None:
    try:
        if not HIVE_MANIFEST_PATH.is_file():
            return None
        data = json.loads(HIVE_MANIFEST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _device_from_manifest(manifest: dict, device_id: str) -> dict | None:
    for d in manifest.get("devices") or []:
        if isinstance(d, dict) and str(d.get("id")) == device_id:
            return d
    return None


def _wg_iface() -> str | None:
    for name in (WG_INTERFACE, "wdtt0", "wg0"):
        if not name:
            continue
        try:
            r = subprocess.run(
                ["ip", "link", "show", name],
                capture_output=True,
                timeout=5,
            )
            if r.returncode == 0:
                return name
        except Exception:
            continue
    return None


def kick_wg_peer(public_key: str) -> bool:
    """Снимает peer с живого wdtt0 — отзыв подписки без HTTP от клиента."""
    pub = (public_key or "").strip()
    if not pub or len(pub) < 40:
        return False
    iface = _wg_iface()
    if not iface:
        logger.warning("wg kick: interface not found")
        return False
    try:
        r = subprocess.run(
            ["wg", "set", iface, "peer", pub, "remove"],
            capture_output=True,
            timeout=10,
        )
        if r.returncode == 0:
            logger.info("wg kick: removed peer %s… on %s", pub[:12], iface)
            return True
        logger.debug("wg kick %s: rc=%s", pub[:12], r.returncode)
        return False
    except Exception as e:
        logger.debug("wg kick %s: %s", pub[:12], e)
        return False


def _valid_pub(pub: str) -> bool:
    p = (pub or "").strip()
    return len(p) >= 40 and all(c.isalnum() or c in "+/=" for c in p)


def _known_device_pubs() -> set[str]:
    m = _load_manifest() or {}
    out: set[str] = set()
    for d in m.get("devices") or []:
        if not isinstance(d, dict):
            continue
        p = (d.get("wg_public_key") or "").strip()
        if _valid_pub(p):
            out.add(p)
    return out


def _local_handshakes() -> list[tuple[str, float | None]]:
    iface = _wg_iface()
    if not iface:
        return []
    try:
        r = subprocess.run(
            ["wg", "show", iface, "latest-handshakes"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    now = time.time()
    out: list[tuple[str, float | None]] = []
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2 or not _valid_pub(parts[0]):
            continue
        try:
            ts = float(parts[1])
        except ValueError:
            continue
        pub = parts[0].strip()
        age = None if ts <= 0 else max(0.0, now - ts)
        out.append((pub, age))
    return out


def wg_peer_counts() -> dict[str, int]:
    total = never_hs = live_3m = 0
    for _pub, age in _local_handshakes():
        total += 1
        if age is None:
            never_hs += 1
        elif age < 180:
            live_3m += 1
    _wg_counts["total"] = total
    _wg_counts["never_hs"] = never_hs
    _wg_counts["live_3m"] = live_3m
    return dict(_wg_counts)


def gc_stale_local_peers(*, grace_sec: float = NEVER_HS_GC_GRACE_SEC, limit: int = GC_LIMIT) -> dict:
    """Снять GETCONF extras: never-hs после grace и handshake >6ч. Ключи из manifest не трогаем."""
    global _last_gc_at
    now = time.time()
    if now - _last_gc_at < GC_EVERY_SEC and grace_sec > 0:
        return {"ok": True, "skipped": True, "removed": 0}
    _last_gc_at = now
    known = _known_device_pubs()
    peers = _local_handshakes()
    never: list[str] = []
    stale: list[str] = []
    for pub, age in peers:
        if pub in known:
            continue
        if age is None:
            never.append(pub)
        elif age >= STALE_EXTRA_HS_SEC:
            stale.append(pub)
    live_never = set(never)
    for pub in list(_pending_never_hs):
        if pub not in live_never:
            _pending_never_hs.pop(pub, None)
    ready_never: list[str] = []
    for pub in never:
        _pending_never_hs.setdefault(pub, now)
        if now - _pending_never_hs[pub] >= grace_sec:
            ready_never.append(pub)
    to_drop = (stale + ready_never)[: max(1, limit)]
    removed = 0
    for pub in to_drop:
        if kick_wg_peer(pub):
            removed += 1
            _pending_never_hs.pop(pub, None)
    _wg_counts["last_removed"] = removed
    if removed:
        logger.info(
            "cell wg gc removed=%s stale=%s never_ready=%s known=%s dump=%s",
            removed,
            len(stale),
            len(ready_never),
            len(known),
            len(peers),
        )
    return {
        "ok": True,
        "removed": removed,
        "stale": len(stale),
        "never_ready": len(ready_never),
        "known": len(known),
        "dump": len(peers),
    }


def apply_manifest_peers(manifest: dict | None = None) -> int:
    """Синхронизирует WireGuard peers из manifest (для VPN без API Улья)."""
    global _last_peer_sync_version
    m = manifest or _load_manifest()
    if not m:
        return 0
    version = int(m.get("version") or 0)
    if version == _last_peer_sync_version:
        return 0
    iface = _wg_iface()
    if not iface:
        logger.warning("standby: wg interface not found")
        return 0
    applied = 0
    for d in m.get("devices") or []:
        if not isinstance(d, dict):
            continue
        pub = (d.get("wg_public_key") or "").strip()
        if not pub or len(pub) < 40:
            continue
        if not bool(d.get("vpn_allowed", True)):
            if kick_wg_peer(pub):
                applied += 1
            continue
        addr = (d.get("wg_address") or "10.66.66.2/32").strip()
        allowed = addr if "/" in addr else f"{addr}/32"
        try:
            subprocess.run(
                ["wg", "set", iface, "peer", pub, "allowed-ips", allowed],
                capture_output=True,
                timeout=10,
                check=True,
            )
            applied += 1
        except Exception as e:
            logger.debug("wg peer %s: %s", pub[:12], e)
    _last_peer_sync_version = version
    if applied:
        logger.info("standby: synced %s wg peer(s), manifest v%s", applied, version)
    return applied


def queen_health_urls(queen_ip: str = "", api_url: str = "") -> list[str]:
    """Сначала прямой IP Улья (без nip.io), потом публичный URL."""
    urls: list[str] = []
    ip = (queen_ip or "").strip()
    if ip:
        urls.append(f"http://{ip}:8000/health")
    api = (api_url or "").strip().rstrip("/")
    if api and api not in urls:
        urls.append(f"{api}/health")
    return urls


def apply_queen_health_tick(
    *,
    now_healthy: bool,
    was_healthy: bool,
    fail_streak: int,
    need: int = QUEEN_FAIL_BEFORE_STANDBY,
) -> tuple[bool, int, str | None]:
    """Решение по DNAT: None / 'standby' / 'queen'. Один фейл health не роняет туннель."""
    if now_healthy:
        if not was_healthy:
            return True, 0, "queen"
        return True, 0, None
    streak = fail_streak + 1
    if was_healthy and streak >= max(1, need):
        return False, streak, "standby"
    return was_healthy, streak, None


async def check_queen_health() -> bool:
    urls = queen_health_urls(HIVE_QUEEN_IP, HIVE_API_URL)
    if not urls:
        return False
    for url in urls:
        try:
            async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
                r = await client.get(url)
            if r.status_code < 500:
                return True
        except Exception:
            continue
    return False


def _iptables_dnat_to_local(enable: bool) -> None:
    """Переключает DNAT 10.66.66.1:8000 → localhost:8000 (standby) или обратно на Улей."""
    if not HIVE_QUEEN_IP:
        return
    queen_dst = f"{HIVE_QUEEN_IP}:8000"
    local_dst = f"127.0.0.1:{STANDBY_API_PORT}"
    target = local_dst if enable else queen_dst
    for table_cmd in (
        ["iptables", "-t", "nat", "-D", "PREROUTING", "-d", TUNNEL_GATEWAY, "-p", "tcp", "--dport", "8000",
         "-j", "DNAT", "--to-destination", queen_dst],
        ["iptables", "-t", "nat", "-D", "PREROUTING", "-d", TUNNEL_GATEWAY, "-p", "tcp", "--dport", "8000",
         "-j", "DNAT", "--to-destination", local_dst],
    ):
        subprocess.run(table_cmd, capture_output=True, timeout=10)
    subprocess.run(
        ["iptables", "-t", "nat", "-A", "PREROUTING", "-d", TUNNEL_GATEWAY, "-p", "tcp", "--dport", "8000",
         "-j", "DNAT", "--to-destination", target],
        capture_output=True,
        timeout=10,
    )


def _write_standby_state(active: bool) -> None:
    STANDBY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STANDBY_STATE_PATH.write_text(
        json.dumps({"standby_active": active, "ts": time.time()}),
        encoding="utf-8",
    )


def create_standby_app() -> FastAPI:
    standby = FastAPI(title="Silent VPN Cell Standby", docs_url=None, redoc_url=None)

    @standby.get("/health")
    async def health():
        return {"status": "ok", "role": "hive-cell-standby", "queen_up": _queen_healthy}

    @standby.get("/api/health")
    async def api_health():
        return {"status": "ok", "role": "hive-cell-standby"}

    @standby.post("/api/vpn/internal/online", response_model=InternalOnlineResponse)
    async def internal_online(
        req: InternalOnlineRequest,
        x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    ):
        secret = INTERNAL_API_SECRET
        if not secret or not secrets.compare_digest(x_internal_secret, secret):
            raise HTTPException(status_code=403, detail="forbidden")
        manifest = _load_manifest()
        if not manifest:
            return InternalOnlineResponse(ok=False, subscription_active=False, vpn_allowed=False)
        dev = _device_from_manifest(manifest, req.device_id.strip())
        if not dev:
            return InternalOnlineResponse(ok=False, subscription_active=False, vpn_allowed=False)
        allowed = bool(dev.get("vpn_allowed", True))
        return InternalOnlineResponse(ok=True, subscription_active=allowed, vpn_allowed=allowed)

    return standby


def _run_standby_uvicorn() -> None:
    import uvicorn

    uvicorn.run(
        create_standby_app(),
        host="127.0.0.1",
        port=STANDBY_API_PORT,
        log_level="warning",
        access_log=False,
    )


def ensure_standby_server() -> None:
    global _standby_server_thread
    if _standby_server_thread and _standby_server_thread.is_alive():
        return
    _standby_server_thread = threading.Thread(target=_run_standby_uvicorn, daemon=True, name="standby-api")
    _standby_server_thread.start()


async def standby_monitor_loop() -> None:
    """Фон: peers из manifest, мониторинг Улья, DNAT на локальный API."""
    global _queen_healthy, _queen_fail_streak
    await asyncio.sleep(8)
    ensure_standby_server()
    # Рестарт агента не должен оставлять DNAT на localhost с прошлого ложного standby.
    _iptables_dnat_to_local(False)
    _write_standby_state(False)
    _queen_healthy = True
    _queen_fail_streak = 0
    logger.warning("standby: start — DNAT на Улей, standby только после %s фейлов health", QUEEN_FAIL_BEFORE_STANDBY)
    while True:
        try:
            apply_manifest_peers()
            gc_stale_local_peers()
            wg_peer_counts()
            healthy = await check_queen_health()
            _queen_healthy, _queen_fail_streak, action = apply_queen_health_tick(
                now_healthy=healthy,
                was_healthy=_queen_healthy,
                fail_streak=_queen_fail_streak,
            )
            if action == "standby":
                logger.warning(
                    "standby: Улей недоступен после %s проверок — локальный API на :%s",
                    _queen_fail_streak,
                    STANDBY_API_PORT,
                )
                _iptables_dnat_to_local(True)
                _write_standby_state(True)
            elif action == "queen":
                logger.warning("standby: Улей снова доступен — DNAT на Улей")
                _iptables_dnat_to_local(False)
                _write_standby_state(False)
        except Exception as e:
            logger.warning("standby monitor: %s", e)
        await asyncio.sleep(15)


def on_manifest_updated(manifest: dict) -> None:
    """Вызывается после POST /v1/sync-manifest."""
    apply_manifest_peers(manifest)
    try:
        theme = manifest.get("theme")
        if isinstance(theme, dict):
            HIVE_THEME_PATH.parent.mkdir(parents=True, exist_ok=True)
            HIVE_THEME_PATH.write_text(json.dumps(theme, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug("standby theme cache: %s", e)


def is_public_failover_path(rest: str) -> bool:
    path = (rest or "").lstrip("/")
    if not path or path.startswith("admin") or path.startswith("vpn/internal"):
        return False
    head = path.split("/", 1)[0]
    return head in ("vpn", "auth", "payments", "health")


def _snapshot_theme() -> dict:
    try:
        if HIVE_THEME_PATH.is_file():
            data = json.loads(HIVE_THEME_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    m = _load_manifest() or {}
    t = m.get("theme")
    return t if isinstance(t, dict) else {}


def _snapshot_hive_meta() -> dict:
    m = _load_manifest() or {}
    meta = m.get("hive_meta")
    if isinstance(meta, dict):
        return meta
    return {"queen_up": _queen_healthy, "role": "hive-cell-standby"}


async def _proxy_queen(request: Request, rest: str) -> Response:
    if not HIVE_API_URL:
        raise HTTPException(status_code=503, detail="HIVE_API_URL not set")
    url = f"{HIVE_API_URL}/api/{rest}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ("host", "content-length", "connection", "transfer-encoding"):
            continue
        headers[k] = v
    body = await request.body()
    timeout = httpx.Timeout(20.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        r = await client.request(request.method, url, headers=headers, content=body)
    skip = {"transfer-encoding", "connection", "content-encoding"}
    out_headers = {k: v for k, v in r.headers.items() if k.lower() not in skip}
    return Response(content=r.content, status_code=r.status_code, headers=out_headers)


def _snapshot_response(rest: str) -> JSONResponse:
    path = (rest or "").lstrip("/")
    if path in ("health",) or path.endswith("health"):
        return JSONResponse({"status": "ok", "role": "hive-cell-standby", "queen_up": False})
    if path in ("vpn/theme",):
        theme = _snapshot_theme()
        if theme:
            return JSONResponse(theme)
        raise HTTPException(status_code=503, detail="Нет снимка оформления")
    if path in ("vpn/hive-meta",):
        return JSONResponse(_snapshot_hive_meta())
    raise HTTPException(
        status_code=503,
        detail="Улей недоступен. Вход и оплата только когда API Улья снова откроется; VPN по снимку уже на этой соте.",
    )


def mount_failover_routes(app: FastAPI) -> None:
    """Публичный failover: клиент ходит на cell-agent :9100 /api/* если Улей не открывается."""

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def hive_public_failover(rest: str, request: Request):
        if not is_public_failover_path(rest):
            raise HTTPException(status_code=404, detail="not found")
        try:
            healthy = await check_queen_health()
        except Exception:
            healthy = False
        if healthy:
            try:
                return await _proxy_queen(request, rest)
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("failover proxy: %s", e)
        return _snapshot_response(rest)
