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
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

HIVE_MANIFEST_PATH = Path("/etc/wdtt/hive_manifest.json")
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


async def check_queen_health() -> bool:
    if not HIVE_API_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            r = await client.get(f"{HIVE_API_URL}/health")
        return r.status_code < 500
    except Exception:
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
    global _queen_healthy
    await asyncio.sleep(8)
    ensure_standby_server()
    while True:
        try:
            apply_manifest_peers()
            healthy = await check_queen_health()
            if healthy != _queen_healthy:
                _queen_healthy = healthy
                if not healthy:
                    logger.warning("standby: Улей недоступен — локальный API на :%s", STANDBY_API_PORT)
                    _iptables_dnat_to_local(True)
                    _write_standby_state(True)
                else:
                    logger.info("standby: Улей снова доступен")
                    _iptables_dnat_to_local(False)
                    _write_standby_state(False)
        except Exception as e:
            logger.warning("standby monitor: %s", e)
        await asyncio.sleep(15)


def on_manifest_updated(manifest: dict) -> None:
    """Вызывается после POST /v1/sync-manifest."""
    apply_manifest_peers(manifest)
