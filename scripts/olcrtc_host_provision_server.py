#!/usr/bin/env python3
"""Host Playwright HTTP для создания комнат Telemost / WB Stream.

Слушает только 127.0.0.1:9101. Docker API ходит через 172.17.0.1 / host.docker.internal.

Запуск (systemd):
  /opt/silent-vpn/olcrtc/host-provision/venv/bin/python olcrtc_host_provision_server.py

Endpoints:
  GET  /health
  GET  /v1/status
  POST /v1/create   {"provider":"telemost"|"wbstream","storage_state"?:{},"headless"?:true}
  POST /v1/storage  {"provider":"...","storage_state":{}}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("olcrtc-host-provision")

HOST = os.environ.get("OLCRTC_HOST_PROVISION_BIND", "127.0.0.1")
PORT = int(os.environ.get("OLCRTC_HOST_PROVISION_PORT", "9101"))
STATE_DIR = Path(
    os.environ.get(
        "OLCRTC_HOST_PROVISION_STATE_DIR",
        "/opt/silent-vpn/olcrtc/agent_states",
    )
)

# ai/ рядом с backend на VPS или локально
_SCRIPT_DIR = Path(__file__).resolve().parent
_CANDIDATE_ROOTS = [
    Path(os.environ.get("OLCRTC_BACKEND_ROOT", "")),
    _SCRIPT_DIR.parent,  # backend/
    Path("/opt/silent-vpn/backend"),
]
for root in _CANDIDATE_ROOTS:
    if root and (root / "ai" / "olcrtc_room_provision.py").is_file():
        sys.path.insert(0, str(root))
        break


def _state_path(provider: str) -> Path:
    return STATE_DIR / f"{provider}_state.json"


def _load_state(provider: str, inline: dict[str, Any] | None) -> dict[str, Any] | None:
    if inline:
        return inline
    path = _state_path(provider)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception as e:
            log.warning("read state %s: %s", path, e)
    return None


def _save_state(provider: str, storage_state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _state_path(provider)
    path.write_text(json.dumps(storage_state, ensure_ascii=False), encoding="utf-8")
    os.chmod(path, 0o600)
    log.info("saved storage_state %s", path)


def _status() -> dict[str, Any]:
    try:
        from ai.olcrtc_room_provision import playwright_available

        pw = playwright_available()
    except Exception:
        pw = False
    return {
        "ok": True,
        "playwright": pw,
        "telemost_state": _state_path("telemost").is_file(),
        "wbstream_state": _state_path("wbstream").is_file(),
        "state_dir": str(STATE_DIR),
        "bind": f"{HOST}:{PORT}",
    }


async def _create(provider: str, storage_state: dict[str, Any] | None, headless: bool) -> dict[str, Any]:
    from ai.olcrtc_room_provision import create_room, playwright_available

    if provider not in ("telemost", "wbstream"):
        return {"ok": False, "message": f"unsupported provider: {provider}"}
    if not playwright_available():
        return {
            "ok": False,
            "message": "playwright/chromium не установлен на хосте (pip install playwright && playwright install chromium)",
        }
    state = _load_state(provider, storage_state)
    if not state:
        return {
            "ok": False,
            "message": f"нет storage_state для {provider} (файл {_state_path(provider)} или body)",
        }
    result = await create_room(provider, state, headless=headless)
    return {
        "ok": result.ok,
        "room_id": result.room_id,
        "message": result.message,
        "provider": provider,
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/"):
            self._send(200, {"ok": True})
            return
        if path == "/v1/status":
            self._send(200, _status())
            return
        self._send(404, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/v1/storage":
            provider = str(body.get("provider") or "").strip().lower()
            state = body.get("storage_state")
            if provider not in ("telemost", "wbstream") or not isinstance(state, dict):
                self._send(400, {"ok": False, "message": "provider + storage_state required"})
                return
            try:
                _save_state(provider, state)
                self._send(200, {"ok": True})
            except Exception as e:
                self._send(500, {"ok": False, "message": str(e)[:200]})
            return
        if path == "/v1/create":
            provider = str(body.get("provider") or "").strip().lower()
            state = body.get("storage_state")
            if not isinstance(state, dict):
                state = None
            headless = bool(body.get("headless", True))
            try:
                result = asyncio.run(_create(provider, state, headless))
                self._send(200 if result.get("ok") else 502, result)
            except Exception as e:
                log.exception("create failed")
                self._send(500, {"ok": False, "message": str(e)[:300]})
            return
        self._send(404, {"ok": False, "message": "not found"})


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info("listening on %s:%s state_dir=%s", HOST, PORT, STATE_DIR)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
