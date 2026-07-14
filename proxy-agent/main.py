"""Silent proxy-agent — health/status/rotate на SOCKS-ноде (не трогает сайт/VPN).

Запуск:
  PROXY_AGENT_SECRET=... PROXY_PUBLIC_IP=1.2.3.4 \\
  PROXY_SOCKS_PORT=1080 PROXY_SOCKS_USER=u PROXY_SOCKS_PASS=p \\
  uvicorn main:app --host 0.0.0.0 --port 9101
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import socket
import subprocess
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Silent Proxy Agent", version="1.0.1")
SECRET = (os.environ.get("PROXY_AGENT_SECRET") or "").strip()
PUBLIC_IP = (os.environ.get("PROXY_PUBLIC_IP") or "").strip()
SOCKS_PORT = int(os.environ.get("PROXY_SOCKS_PORT") or "1080")
SOCKS_USER = (os.environ.get("PROXY_SOCKS_USER") or "").strip()
SOCKS_PASS = (os.environ.get("PROXY_SOCKS_PASS") or "").strip()
HTTP_PORT = int(os.environ.get("PROXY_HTTP_PORT") or "0")
HTTP_USER = (os.environ.get("PROXY_HTTP_USER") or "").strip()
HTTP_PASS = (os.environ.get("PROXY_HTTP_PASS") or "").strip()
MTPROTO_PORT = int(os.environ.get("PROXY_MTPROTO_PORT") or "0")
MTPROTO_SECRET = (os.environ.get("PROXY_MTPROTO_SECRET") or "").strip()
BUILD_PATH = Path(__file__).resolve()
SINGBOX_CFG = Path("/etc/silent-proxy/sing-box.json")
AGENT_ENV = Path("/etc/silent-proxy/agent.env")
PORT_MIN = int(os.environ.get("PROXY_PORT_MIN") or "20000")
PORT_MAX = int(os.environ.get("PROXY_PORT_MAX") or "50000")


def agent_build_id() -> str:
    try:
        data = BUILD_PATH.read_bytes()
    except OSError:
        data = b""
    return hashlib.sha256(data).hexdigest()[:16]


def _auth(secret: str | None) -> None:
    if not SECRET or secret != SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")


def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.bind(("0.0.0.0", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def _systemctl_active(unit: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _run(cmd: list[str] | str, timeout: int = 60) -> str:
    if isinstance(cmd, str):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    else:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout or "") + (r.stderr or "")


def _reload_env_from_file() -> None:
    global SOCKS_PORT, SOCKS_USER, SOCKS_PASS, SECRET, PUBLIC_IP
    if not AGENT_ENV.is_file():
        return
    for line in AGENT_ENV.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k == "PROXY_SOCKS_PORT":
            SOCKS_PORT = int(v)
        elif k == "PROXY_SOCKS_USER":
            SOCKS_USER = v
        elif k == "PROXY_SOCKS_PASS":
            SOCKS_PASS = v
        elif k == "PROXY_AGENT_SECRET":
            SECRET = v
        elif k == "PROXY_PUBLIC_IP":
            PUBLIC_IP = v


class RotateRequest(BaseModel):
    new_port: int | None = Field(default=None, ge=1024, le=65535)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "role": "silent-proxy-agent",
        "agent_build_id": agent_build_id(),
        "socks_port": SOCKS_PORT,
    }


@app.get("/v1/status")
async def status(x_proxy_agent_secret: str | None = Header(default=None)):
    _auth(x_proxy_agent_secret)
    socks_up = _systemctl_active("silent-socks.service")
    mt_up = _systemctl_active("silent-mtproto.service") if MTPROTO_PORT else False
    socks_listening = _port_in_use(SOCKS_PORT)
    http_listening = _port_in_use(HTTP_PORT) if HTTP_PORT else False
    mt_listening = _port_in_use(MTPROTO_PORT) if MTPROTO_PORT else False
    ok = socks_up and socks_listening and (not HTTP_PORT or http_listening)
    return {
        "status": "ok" if ok else "degraded",
        "public_ip": PUBLIC_IP,
        "socks_port": SOCKS_PORT,
        "socks_user": SOCKS_USER,
        "socks_listening": bool(socks_listening),
        "socks_service": socks_up,
        "http_port": HTTP_PORT or None,
        "http_listening": bool(http_listening) if HTTP_PORT else None,
        "mtproto_port": MTPROTO_PORT or None,
        "mtproto_listening": bool(mt_listening) if MTPROTO_PORT else None,
        "mtproto_service": mt_up if MTPROTO_PORT else None,
        "agent_build_id": agent_build_id(),
    }


@app.get("/v1/endpoint")
async def endpoint(x_proxy_agent_secret: str | None = Header(default=None)):
    _auth(x_proxy_agent_secret)
    data = {
        "host": PUBLIC_IP,
        "port": SOCKS_PORT,
        "username": SOCKS_USER,
        "password": SOCKS_PASS,
        "scheme": "socks5",
        "url": f"socks5://{SOCKS_USER}:{SOCKS_PASS}@{PUBLIC_IP}:{SOCKS_PORT}",
        "socks_url": f"socks5://{SOCKS_USER}:{SOCKS_PASS}@{PUBLIC_IP}:{SOCKS_PORT}",
    }
    if HTTP_PORT and HTTP_USER:
        data["http_port"] = HTTP_PORT
        data["http_user"] = HTTP_USER
        data["http_password"] = HTTP_PASS
        data["http_url"] = f"http://{HTTP_USER}:{HTTP_PASS}@{PUBLIC_IP}:{HTTP_PORT}"
    if MTPROTO_PORT and MTPROTO_SECRET:
        data["mtproto_port"] = MTPROTO_PORT
        data["mtproto_secret"] = MTPROTO_SECRET
        data["telegram_link"] = (
            f"tg://proxy?server={PUBLIC_IP}&port={MTPROTO_PORT}&secret={MTPROTO_SECRET}"
        )
    return data


@app.post("/v1/rotate-port")
async def rotate_port(
    req: RotateRequest | None = None,
    x_proxy_agent_secret: str | None = Header(default=None),
):
    """Смена SOCKS-порта при блоке. Не трогает сайты/docker — только silent-socks + ufw."""
    global SOCKS_PORT
    _auth(x_proxy_agent_secret)
    old = SOCKS_PORT
    wanted = (req.new_port if req else None) or None
    if wanted is None:
        for _ in range(40):
            cand = random.randint(PORT_MIN, PORT_MAX)
            if cand != old and not _port_in_use(cand):
                wanted = cand
                break
    if wanted is None:
        raise HTTPException(500, "cannot find free port")
    if wanted == old:
        return {"ok": True, "port": old, "changed": False}

    if not SINGBOX_CFG.is_file():
        raise HTTPException(500, "sing-box config missing")

    cfg = json.loads(SINGBOX_CFG.read_text(encoding="utf-8"))
    for inbound in cfg.get("inbounds") or []:
        if inbound.get("type") == "socks":
            inbound["listen_port"] = int(wanted)
    SINGBOX_CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # update agent.env
    lines = []
    if AGENT_ENV.is_file():
        for line in AGENT_ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith("PROXY_SOCKS_PORT="):
                lines.append(f"PROXY_SOCKS_PORT={wanted}")
            else:
                lines.append(line)
    else:
        lines = [
            f"PROXY_AGENT_SECRET={SECRET}",
            f"PROXY_PUBLIC_IP={PUBLIC_IP}",
            f"PROXY_SOCKS_PORT={wanted}",
            f"PROXY_SOCKS_USER={SOCKS_USER}",
            f"PROXY_SOCKS_PASS={SOCKS_PASS}",
        ]
    AGENT_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(AGENT_ENV, 0o600)
    except OSError:
        pass

    _run(f"ufw allow {int(wanted)}/tcp || true")
    _run("systemctl restart silent-socks.service")
    # verify
    import time

    time.sleep(1.5)
    if not _systemctl_active("silent-socks.service"):
        raise HTTPException(500, "silent-socks failed after rotate")
    SOCKS_PORT = int(wanted)
    return {
        "ok": True,
        "changed": True,
        "old_port": old,
        "port": SOCKS_PORT,
        "url": f"socks5://{SOCKS_USER}:{SOCKS_PASS}@{PUBLIC_IP}:{SOCKS_PORT}",
    }
