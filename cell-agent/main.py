"""Cell-agent — лёгкий HTTP-сервис на VPN-соте для handshake с Ульем.

Запуск на соте:
  export CELL_AGENT_SECRET='длинный-случайный-пароль'
  export CELL_PUBLIC_IP='1.2.3.4'
  export WG_SERVER_PUBLIC_KEY='...'
  export HIVE_API_URL='https://132-243-234-162.nip.io'
  uvicorn main:app --host 0.0.0.0 --port 9100

Пароль CELL_AGENT_SECRET вводится в админке «Улей» при подключении соты.
"""
from __future__ import annotations

import json
import os
import secrets
import hashlib
from pathlib import Path
from typing import Any, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

try:
    from standby_runtime import on_manifest_updated, standby_monitor_loop
except ImportError:
    on_manifest_updated = None  # type: ignore
    standby_monitor_loop = None  # type: ignore


@asynccontextmanager
async def _lifespan(application: FastAPI):
    task = None
    if standby_monitor_loop is not None:
        import asyncio

        task = asyncio.create_task(standby_monitor_loop())
    yield
    if task is not None:
        task.cancel()
        try:
            await task
        except Exception:
            pass


app = FastAPI(title="Silent VPN Cell Agent", docs_url=None, redoc_url=None, lifespan=_lifespan)

CELL_AGENT_SECRET = (os.environ.get("CELL_AGENT_SECRET") or "").strip()
CELL_PUBLIC_IP = (os.environ.get("CELL_PUBLIC_IP") or "").strip()
WG_SERVER_PUBLIC_KEY = (os.environ.get("WG_SERVER_PUBLIC_KEY") or "").strip()
WDTT_PORT = int(os.environ.get("WDTT_PORT", "56000"))
WG_PORT = int(os.environ.get("WG_PORT", "56001"))
HIVE_API_URL = (os.environ.get("HIVE_API_URL") or "").strip().rstrip("/")
TUNNEL_API_URL = (os.environ.get("TUNNEL_API_URL") or "http://10.66.66.1:8000").strip()
CELL_LINK_CAPACITY_MBPS = float(os.environ.get("CELL_LINK_CAPACITY_MBPS") or "1000")
CELL_NETWORK_INTERFACE = (os.environ.get("CELL_NETWORK_INTERFACE") or "").strip()


def agent_build_id() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


def _auth(secret: str) -> None:
    expected = CELL_AGENT_SECRET
    if not expected or len(expected) < 8:
        raise HTTPException(status_code=503, detail="CELL_AGENT_SECRET not configured")
    if not secret or not secrets.compare_digest(secret, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def _pick_olcrtc2_dns(preferred: str = "") -> str:
    """Prefer local caching DNS; fallback to resolv.conf or Yandex."""
    cand = (preferred or "").strip()
    if cand and ":" not in cand:
        cand = f"{cand}:53"
    if cand:
        return cand

    try:
        import socket

        with socket.create_connection(("127.0.0.1", 53), timeout=0.25):
            return "127.0.0.1:53"
    except Exception:
        pass

    try:
        resolv = Path("/etc/resolv.conf")
        if resolv.is_file():
            for line in resolv.read_text(encoding="utf-8", errors="ignore").splitlines():
                s = line.strip()
                if not s.startswith("nameserver "):
                    continue
                ip = s.split(maxsplit=1)[1].strip()
                if ip and ":" not in ip:
                    return f"{ip}:53"
    except Exception:
        pass

    return "77.88.8.8:53"


def _detect_public_ip() -> str:
    if CELL_PUBLIC_IP:
        return CELL_PUBLIC_IP
    try:
        import urllib.request

        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as resp:
            return resp.read().decode().strip()
    except Exception:
        return ""


@app.get("/health")
async def health():
    return {"status": "ok", "role": "hive-cell-agent", "agent_build_id": agent_build_id()}


@app.post("/v1/handshake")
async def handshake(
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    """Улей проверяет соту и получает параметры VPN."""
    _auth(x_cell_agent_secret)
    pub_ip = _detect_public_ip()
    if not pub_ip:
        raise HTTPException(status_code=503, detail="CELL_PUBLIC_IP not set")
    if not WG_SERVER_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="WG_SERVER_PUBLIC_KEY not set")
    return {
        "public_ip": pub_ip,
        "wg_public_key": WG_SERVER_PUBLIC_KEY,
        "wdtt_port": WDTT_PORT,
        "wg_port": WG_PORT,
        "tunnel_api_url": TUNNEL_API_URL,
        "hive_api_url": HIVE_API_URL,
    }


class ConfigureRequest(BaseModel):
    hive_api_url: Optional[str] = None
    internal_api_secret: Optional[str] = None
    hive_cell_id: Optional[str] = None


@app.post("/v1/configure")
async def configure(
    req: ConfigureRequest,
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    """Улей может передать runtime-конфиг (будущее: запись в env wdtt)."""
    _auth(x_cell_agent_secret)
    return {
        "ok": True,
        "message": "configure accepted (apply wdtt env manually or via deploy script)",
        "received": {
            "hive_api_url": bool(req.hive_api_url),
            "hive_cell_id": bool(req.hive_cell_id),
        },
    }


def _read_linux_load(*, cpu_interval: float = 0.2) -> tuple[float, float]:
    """CPU/RAM через /proc (без psutil)."""
    cpu_percent = 0.0
    memory_percent = 0.0
    try:
        with open("/proc/meminfo", encoding="utf-8", errors="replace") as f:
            total_kb = avail_kb = 0
            for line in f:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = int(line.split()[1])
            if total_kb > 0:
                memory_percent = round(max(0.0, min(100.0, (1 - avail_kb / total_kb) * 100)), 1)
    except OSError:
        pass

    try:
        def cpu_idle() -> tuple[int, int]:
            with open("/proc/stat", encoding="utf-8", errors="replace") as f:
                parts = f.readline().split()
            vals = [int(x) for x in parts[1:]]
            return sum(vals), vals[3] + vals[4]

        t1, i1 = cpu_idle()
        import time

        time.sleep(cpu_interval)
        t2, i2 = cpu_idle()
        dt, di = t2 - t1, i2 - i1
        if dt > 0:
            cpu_percent = round(max(0.0, min(100.0, (1 - di / dt) * 100)), 1)
    except OSError:
        pass
    return cpu_percent, memory_percent


def _default_iface() -> str:
    if CELL_NETWORK_INTERFACE:
        return CELL_NETWORK_INTERFACE
    try:
        with open("/proc/net/route", encoding="utf-8", errors="replace") as f:
            next(f, None)
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "00000000" and parts[3] != "0000":
                    return parts[0]
    except OSError:
        return ""
    return ""


def _read_net_bytes(iface: str) -> tuple[int, int]:
    with open("/proc/net/dev", encoding="utf-8", errors="replace") as f:
        for line in f:
            row = line.strip()
            if ":" not in row:
                continue
            name, rest = row.split(":", 1)
            if name.strip() != iface:
                continue
            vals = rest.split()
            if len(vals) >= 16:
                return int(vals[0]), int(vals[8])
    return 0, 0


def _iface_speed_mbps(iface: str) -> tuple[float, float | None]:
    """(эффективная ёмкость, sysfs Мбит/с или None)."""
    try:
        with open(f"/sys/class/net/{iface}/speed", encoding="utf-8", errors="replace") as f:
            speed = float(f.read().strip())
            if speed > 0:
                return speed, speed
    except Exception:
        pass
    return max(1.0, CELL_LINK_CAPACITY_MBPS), None


def _network_status(interval: float = 0.2) -> tuple[str | None, float, float, float, float, float | None]:
    iface = _default_iface()
    if not iface:
        return None, 0.0, 0.0, 0.0, max(1.0, CELL_LINK_CAPACITY_MBPS), None
    rx1, tx1 = _read_net_bytes(iface)
    import time
    time.sleep(interval)
    rx2, tx2 = _read_net_bytes(iface)
    rx_mbps = max(0.0, (rx2 - rx1) * 8.0 / interval / 1_000_000.0)
    tx_mbps = max(0.0, (tx2 - tx1) * 8.0 / interval / 1_000_000.0)
    cap, sysfs_cap = _iface_speed_mbps(iface)
    util = min(100.0, (max(rx_mbps, tx_mbps) / max(1.0, cap)) * 100.0)
    return iface, round(rx_mbps, 1), round(tx_mbps, 1), round(util, 1), round(cap, 1), sysfs_cap


def _memory_total_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024, 1)
    except OSError:
        pass
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        return 0.0


@app.get("/v1/status")
async def status(
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    _auth(x_cell_agent_secret)
    wdtt_active = False
    cpu_percent = 0.0
    memory_percent = 0.0
    network_interface = None
    network_mbps_rx = 0.0
    network_mbps_tx = 0.0
    network_util_percent = 0.0
    network_link_capacity_mbps = max(1.0, CELL_LINK_CAPACITY_MBPS)
    network_link_sysfs_mbps: float | None = None
    try:
        import subprocess

        r = subprocess.run(
            ["systemctl", "is-active", "wdtt"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        wdtt_active = r.stdout.strip() == "active"
    except Exception:
        pass
    try:
        import psutil

        cpu_percent = round(float(psutil.cpu_percent(interval=0.2)), 1)
        memory_percent = round(float(psutil.virtual_memory().percent), 1)
    except Exception:
        cpu_percent, memory_percent = _read_linux_load(cpu_interval=0.2)
    try:
        network_interface, network_mbps_rx, network_mbps_tx, network_util_percent, network_link_capacity_mbps, network_link_sysfs_mbps = _network_status(0.2)
    except Exception:
        pass
    cpu_cores = 1
    try:
        import os

        cpu_cores = max(1, os.cpu_count() or 1)
    except Exception:
        pass
    wg_key = WG_SERVER_PUBLIC_KEY
    if not wg_key:
        try:
            from pathlib import Path

            p = Path("/etc/wdtt/wg_public.key")
            if p.is_file():
                wg_key = p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    olcrtc_units = 0
    olcrtc_active = 0
    try:
        import subprocess

        r = subprocess.run(
            ["systemctl", "list-units", "olcrtc@*.service", "--no-legend", "--state=active"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        lines = [ln for ln in (r.stdout or "").splitlines() if "olcrtc@" in ln]
        olcrtc_active = len(lines)
        r2 = subprocess.run(
            ["systemctl", "list-unit-files", "olcrtc@*.service", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        olcrtc_units = len(
            [ln for ln in (r2.stdout or "").splitlines() if "olcrtc@" in ln]
        )
    except Exception:
        pass

    return {
        "public_ip": _detect_public_ip(),
        "wdtt_active": wdtt_active,
        "wg_public_key": wg_key,
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "network_interface": network_interface,
        "network_mbps_rx": network_mbps_rx,
        "network_mbps_tx": network_mbps_tx,
        "network_util_percent": network_util_percent,
        "network_link_capacity_mbps": network_link_capacity_mbps,
        "network_link_sysfs_mbps": network_link_sysfs_mbps,
        "cpu_cores": cpu_cores,
        "memory_total_gb": _memory_total_gb(),
        "agent_build_id": agent_build_id(),
        "olcrtc_units": olcrtc_units,
        "olcrtc_peers_est": olcrtc_active,
        "olcrtc_active_units": olcrtc_active,
    }


class OlcrtcApplyBody(BaseModel):
    unit_name: str
    yaml_text: str
    restart: bool = True


@app.post("/v1/olcrtc/apply")
async def olcrtc_apply(
    body: OlcrtcApplyBody,
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    """Улей пушит server-{unit}.yaml и перезапускает olcrtc@unit на соте."""
    _auth(x_cell_agent_secret)
    import re
    import subprocess

    unit = (body.unit_name or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,120}", unit):
        raise HTTPException(status_code=400, detail="bad unit_name")
    if not (body.yaml_text or "").strip():
        raise HTTPException(status_code=400, detail="yaml_text empty")
    root = Path("/opt/silent-vpn/olcrtc")
    root.mkdir(parents=True, exist_ok=True)
    (root / f"data-{unit}").mkdir(parents=True, exist_ok=True)
    path = root / f"server-{unit}.yaml"
    path.write_text(body.yaml_text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    if body.restart:
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=30)
        subprocess.run(
            ["systemctl", "enable", f"olcrtc@{unit}.service"],
            capture_output=True,
            timeout=30,
        )
        r = subprocess.run(
            ["systemctl", "restart", f"olcrtc@{unit}.service"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=(r.stderr or r.stdout or "restart failed")[:300],
            )
    return {"ok": True, "unit": unit, "path": str(path)}


class Olcrtc2ApplyBody(BaseModel):
    unit_name: str
    room: str
    crypto_key: str
    provider: str = "telemost"
    auth_token: str = ""  # WB account JWT for srv (required for wbstream)
    olcrtc_dns: str = ""  # e.g. 127.0.0.1:53 (local cache resolver on cell)
    restart: bool = True


class Olcrtc2TeardownBody(BaseModel):
    unit_name: str


class Olcrtc2CreateBody(BaseModel):
    provider: str = "telemost"
    storage_state: dict[str, Any] = {}


@app.post("/v1/olcrtc2/apply")
async def olcrtc2_apply(
    body: Olcrtc2ApplyBody,
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    """Per-session olcrtc2@unit: env + restart (Telemost exit on cell, not queen)."""
    _auth(x_cell_agent_secret)
    import re
    import subprocess

    unit = (body.unit_name or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,120}", unit):
        raise HTTPException(status_code=400, detail="bad unit_name")
    room = (body.room or "").strip()
    key = (body.crypto_key or "").strip().lower()
    if not room or len(key) != 64:
        raise HTTPException(status_code=400, detail="room and 64-hex crypto_key required")
    prov = (body.provider or "telemost").strip().lower()
    mode = "wbstream" if prov == "wbstream" else "telemost"
    auth_token = (body.auth_token or "").strip()
    import logging as _logging

    _logging.getLogger("uvicorn.error").info(
        "olcrtc2_apply unit=%s provider=%r mode=%s tok_len=%s room=%s",
        unit,
        body.provider,
        mode,
        len(auth_token),
        room[:40],
    )
    if mode == "wbstream" and not auth_token.startswith("eyJ"):
        raise HTTPException(
            status_code=400,
            detail="wbstream requires auth_token (account JWT eyJ…)",
        )
    root = Path("/opt/silent-vpn/olcrtc2")
    env_dir = root / "env.d"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_path = env_dir / f"{unit}.env"
    lines = [
        f"OLCRTC2_MODE={mode}",
        f"OLCRTC2_ROOM={room}",
        f"OLCRTC2_KEY={key}",
        f"OLCRTC2_DNS={_pick_olcrtc2_dns(body.olcrtc_dns)}",
    ]
    if auth_token:
        # escape newlines in JWT (should be single line)
        lines.append(f"OLCRTC2_AUTH_TOKEN={auth_token.replace(chr(10), '').replace(chr(13), '')}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    # Ensure template unit exists
    unit_path = Path("/etc/systemd/system/olcrtc2@.service")
    # Без CPUQuota=50%: Telemost/vp8 упирается в пол-ядра → секундные «зависания».
    desired_unit = f"""[Unit]
Description=Silent VPN olcrtc2-srv %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={root}
EnvironmentFile=-{root}/env.d/%i.env
ExecStart={root}/olcrtc2-srv
Restart=on-failure
RestartSec=5
MemoryMax=1G
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
    cur_unit = unit_path.read_text(encoding="utf-8") if unit_path.is_file() else ""
    if cur_unit != desired_unit:
        unit_path.write_text(desired_unit, encoding="utf-8")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=30)
    if body.restart:
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=30)
        subprocess.run(
            ["systemctl", "enable", f"olcrtc2@{unit}.service"],
            capture_output=True,
            timeout=30,
        )
        r = subprocess.run(
            ["systemctl", "restart", f"olcrtc2@{unit}.service"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=(r.stderr or r.stdout or "restart failed")[:300],
            )
        active = subprocess.run(
            ["systemctl", "is-active", f"olcrtc2@{unit}.service"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if (active.stdout or "").strip() != "active":
            raise HTTPException(status_code=500, detail="unit not active after restart")
    return {"ok": True, "unit": unit, "env": str(env_path)}


class Olcrtc2StatusBody(BaseModel):
    unit_name: str = ""


@app.post("/v1/olcrtc2/status")
async def olcrtc2_status(
    body: Olcrtc2StatusBody,
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    """is-active + env presence — queen не выдаёт комнату с мёртвым srv."""
    _auth(x_cell_agent_secret)
    import re
    import subprocess

    unit = (body.unit_name or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,120}", unit):
        raise HTTPException(status_code=400, detail="bad unit_name")
    env_path = Path(f"/opt/silent-vpn/olcrtc2/env.d/{unit}.env")
    active = subprocess.run(
        ["systemctl", "is-active", f"olcrtc2@{unit}.service"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    state = (active.stdout or "").strip()
    has_env = env_path.is_file()
    room = ""
    if has_env:
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("OLCRTC2_ROOM="):
                    room = line.split("=", 1)[1].strip()
                    break
        except OSError:
            pass
    return {
        "ok": True,
        "unit": unit,
        "active": state == "active",
        "state": state,
        "has_env": has_env,
        "room": room[:80],
    }


@app.post("/v1/olcrtc2/teardown")
async def olcrtc2_teardown(
    body: Olcrtc2TeardownBody,
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    _auth(x_cell_agent_secret)
    import re
    import subprocess

    unit = (body.unit_name or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,120}", unit):
        raise HTTPException(status_code=400, detail="bad unit_name")
    subprocess.run(
        ["systemctl", "stop", f"olcrtc2@{unit}.service"],
        capture_output=True,
        timeout=60,
    )
    subprocess.run(
        ["systemctl", "disable", f"olcrtc2@{unit}.service"],
        capture_output=True,
        timeout=30,
    )
    env_path = Path(f"/opt/silent-vpn/olcrtc2/env.d/{unit}.env")
    try:
        env_path.unlink(missing_ok=True)
    except TypeError:
        if env_path.is_file():
            env_path.unlink()
    except OSError:
        pass
    return {"ok": True, "unit": unit}


@app.post("/v1/olcrtc2/create")
async def olcrtc2_create(
    body: Olcrtc2CreateBody,
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    """Create Telemost room on CELL (Playwright). Never run this on WDTT queen."""
    _auth(x_cell_agent_secret)
    provider = (body.provider or "telemost").strip().lower()
    if provider != "telemost":
        raise HTTPException(status_code=400, detail="cell create supports telemost only")
    # Prefer local host-provision on same machine :9101
    try:
        import httpx

        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                "http://127.0.0.1:9101/v1/create",
                json={
                    "provider": "telemost",
                    "storage_state": body.storage_state or {},
                    "headless": True,
                },
            )
        if r.status_code == 200:
            data = r.json() if r.content else {}
            room_id = str(data.get("room_id") or data.get("room") or "").strip()
            if data.get("ok") and room_id:
                return {"ok": True, "room_id": room_id, "message": data.get("message") or "ok"}
            return {
                "ok": False,
                "message": str(data.get("message") or data.get("detail") or r.text)[:300],
            }
        return {"ok": False, "message": f"local provision HTTP {r.status_code}: {(r.text or '')[:200]}"}
    except Exception as e:
        return {
            "ok": False,
            "message": (
                f"Playwright create unavailable on cell: {e}. "
                "Deploy silent-olcrtc-host-provision on this cell (:9101)."
            )[:300],
        }


HIVE_MANIFEST_PATH = Path("/etc/wdtt/hive_manifest.json")


class WgKickRequest(BaseModel):
    wg_public_key: str


@app.post("/v1/wg/kick")
async def wg_kick(
    req: WgKickRequest,
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    """Улей снимает живой WG peer при отзыве подписки."""
    _auth(x_cell_agent_secret)
    try:
        from standby_runtime import kick_wg_peer
    except ImportError:
        kick_wg_peer = None  # type: ignore
    if kick_wg_peer is None:
        raise HTTPException(status_code=503, detail="standby_runtime unavailable")
    ok = bool(kick_wg_peer(req.wg_public_key))
    return {"ok": ok}


@app.post("/v1/sync-manifest")
async def sync_manifest(
    payload: dict[str, Any],
    x_cell_agent_secret: str = Header(default="", alias="X-Cell-Agent-Secret"),
):
    """Улей пушит список устройств соты (для автономии при падении API)."""
    _auth(x_cell_agent_secret)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid manifest")
    HIVE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = HIVE_MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, HIVE_MANIFEST_PATH)
    if on_manifest_updated is not None:
        on_manifest_updated(payload)
    return {"ok": True, "version": payload.get("version"), "device_count": payload.get("device_count")}
