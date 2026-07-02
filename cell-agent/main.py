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

import os
import secrets
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Silent VPN Cell Agent", docs_url=None, redoc_url=None)

CELL_AGENT_SECRET = (os.environ.get("CELL_AGENT_SECRET") or "").strip()
CELL_PUBLIC_IP = (os.environ.get("CELL_PUBLIC_IP") or "").strip()
WG_SERVER_PUBLIC_KEY = (os.environ.get("WG_SERVER_PUBLIC_KEY") or "").strip()
WDTT_PORT = int(os.environ.get("WDTT_PORT", "56000"))
WG_PORT = int(os.environ.get("WG_PORT", "56001"))
HIVE_API_URL = (os.environ.get("HIVE_API_URL") or "").strip().rstrip("/")
TUNNEL_API_URL = (os.environ.get("TUNNEL_API_URL") or "http://10.66.66.1:8000").strip()
CELL_LINK_CAPACITY_MBPS = float(os.environ.get("CELL_LINK_CAPACITY_MBPS") or "1000")
CELL_NETWORK_INTERFACE = (os.environ.get("CELL_NETWORK_INTERFACE") or "").strip()


def _auth(secret: str) -> None:
    expected = CELL_AGENT_SECRET
    if not expected or len(expected) < 8:
        raise HTTPException(status_code=503, detail="CELL_AGENT_SECRET not configured")
    if not secret or not secrets.compare_digest(secret, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


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
    return {"status": "ok", "role": "hive-cell-agent"}


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


def _iface_speed_mbps(iface: str) -> float:
    try:
        with open(f"/sys/class/net/{iface}/speed", encoding="utf-8", errors="replace") as f:
            speed = float(f.read().strip())
            if speed > 0:
                return speed
    except Exception:
        pass
    return max(1.0, CELL_LINK_CAPACITY_MBPS)


def _network_status(interval: float = 0.2) -> tuple[str | None, float, float, float, float]:
    iface = _default_iface()
    if not iface:
        return None, 0.0, 0.0, 0.0, max(1.0, CELL_LINK_CAPACITY_MBPS)
    rx1, tx1 = _read_net_bytes(iface)
    import time
    time.sleep(interval)
    rx2, tx2 = _read_net_bytes(iface)
    rx_mbps = max(0.0, (rx2 - rx1) * 8.0 / interval / 1_000_000.0)
    tx_mbps = max(0.0, (tx2 - tx1) * 8.0 / interval / 1_000_000.0)
    cap = _iface_speed_mbps(iface)
    util = min(100.0, (max(rx_mbps, tx_mbps) / max(1.0, cap)) * 100.0)
    return iface, round(rx_mbps, 1), round(tx_mbps, 1), round(util, 1), round(cap, 1)


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
        network_interface, network_mbps_rx, network_mbps_tx, network_util_percent, network_link_capacity_mbps = _network_status(0.2)
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
    }
