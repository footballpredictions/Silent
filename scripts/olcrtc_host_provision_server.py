#!/usr/bin/env python3
"""Host Playwright HTTP для создания комнат Telemost / WB Stream.

Bind: 0.0.0.0:9101 (Docker bridge → host), UFW только 172.16.0.0/12.
Auth: X-Internal-Secret = INTERNAL_API_SECRET (как у S2S API).

Endpoints:
  GET  /health          — без секрета (liveness)
  GET  /v1/status       — нужен секрет
  GET  /v1/unit-health?unit=android-wbstream — нужен секрет
  POST /v1/create       — нужен секрет
  POST /v1/storage      — нужен секрет
  POST /v1/units/apply  — нужен секрет; yaml + systemctl enable/stop для комнат
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("olcrtc-host-provision")

HOST = os.environ.get("OLCRTC_HOST_PROVISION_BIND", "127.0.0.1")
PORT = int(os.environ.get("OLCRTC_HOST_PROVISION_PORT", "9101"))
# Совпадает с backend INTERNAL_API_SECRET (EnvironmentFile .env).
INTERNAL_SECRET = (
    os.environ.get("OLCRTC_HOST_PROVISION_SECRET")
    or os.environ.get("INTERNAL_API_SECRET")
    or ""
).strip()
STATE_DIR = Path(
    os.environ.get(
        "OLCRTC_HOST_PROVISION_STATE_DIR",
        "/opt/silent-vpn/olcrtc/agent_states",
    )
)
# Где живут бинарь, server-<unit>.yaml и data-<unit>/ для olcrtc@<unit>.
OLCRTC_DIR = Path(os.environ.get("OLCRTC_DIR", "/opt/silent-vpn/olcrtc"))
UNIT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$", re.I)
# ThreadingHTTPServer иначе поднимает N Chromium параллельно → CPU 100% + RAM 6G+.
_CREATE_SEM = threading.Semaphore(
    max(1, int(os.environ.get("OLCRTC_HOST_CREATE_PARALLEL", "1")))
)
_CREATE_WAIT_SEC = max(30, int(os.environ.get("OLCRTC_HOST_CREATE_WAIT_SEC", "180")))

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
        "auth_required": bool(INTERNAL_SECRET),
    }


def _systemctl(*args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["systemctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()[:300]
    except Exception as e:
        return 1, str(e)[:200]


def _apply_units(units: dict[str, str], remove: list[str]) -> dict[str, Any]:
    """YAML + systemd для комнат пула: агент поднимает/гасит unit'ы сам."""
    if not OLCRTC_DIR.is_dir():
        return {"ok": False, "message": f"нет {OLCRTC_DIR}"}
    binary = OLCRTC_DIR / "olcrtc"
    if not binary.is_file():
        return {"ok": False, "message": f"нет бинаря {binary}"}

    applied: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed_units: list[str] = []

    for unit, yaml_text in (units or {}).items():
        name = (unit or "").strip()
        if not UNIT_NAME_RE.match(name) or not isinstance(yaml_text, str) or not yaml_text.strip():
            applied.append({"unit": name, "ok": False, "message": "bad unit/yaml"})
            continue
        path = OLCRTC_DIR / f"server-{name}.yaml"
        try:
            previous = path.read_text(encoding="utf-8") if path.is_file() else ""
            if previous != yaml_text:
                path.write_text(yaml_text, encoding="utf-8")
                os.chmod(path, 0o600)
                changed_units.append(name)
            (OLCRTC_DIR / f"data-{name}").mkdir(parents=True, exist_ok=True)
        except Exception as e:
            applied.append({"unit": name, "ok": False, "message": str(e)[:150]})
            continue
        svc = f"olcrtc@{name}.service"
        code, out = _systemctl("is-active", svc, timeout=10)
        needs_start = out.strip() != "active" or name in changed_units
        if needs_start:
            _systemctl("enable", svc, timeout=20)
            code, out = _systemctl("restart", svc, timeout=60)
        else:
            code, out = 0, "already active"
        applied.append({"unit": name, "ok": code == 0, "message": out[:150]})

    for unit in remove or []:
        name = (unit or "").strip()
        if not UNIT_NAME_RE.match(name):
            continue
        svc = f"olcrtc@{name}.service"
        code, out = _systemctl("disable", "--now", svc, timeout=45)
        try:
            (OLCRTC_DIR / f"server-{name}.yaml").unlink(missing_ok=True)
            data_dir = OLCRTC_DIR / f"data-{name}"
            if data_dir.is_dir():
                shutil.rmtree(data_dir, ignore_errors=True)
        except Exception as e:
            out = f"{out}; files: {e}"[:200]
        removed.append({"unit": name, "ok": True, "message": out[:150]})

    if changed_units or removed:
        _systemctl("daemon-reload", timeout=30)
    return {
        "ok": True,
        "applied": applied,
        "removed": removed,
        "started": sum(1 for a in applied if a.get("ok")),
        "stopped": len(removed),
    }


def _unit_health(unit: str) -> dict[str, Any]:
    """systemd + journal: host реально в комнате (Link connected) или нет."""
    name = (unit or "").strip()
    if not name or not re.match(r"^[a-z0-9._-]+$", name, re.I):
        return {"ok": False, "message": "bad unit"}
    svc = f"olcrtc@{name}.service"
    try:
        active = (
            subprocess.check_output(
                ["systemctl", "is-active", svc],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
            .strip()
        )
    except Exception:
        active = "unknown"
    journal = ""
    try:
        journal = subprocess.check_output(
            [
                "journalctl",
                "-u",
                svc,
                "-n",
                "40",
                "--no-pager",
                "-o",
                "cat",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=8,
        )
    except Exception as e:
        return {
            "ok": False,
            "unit": name,
            "active": active,
            "healthy": None,  # неизвестно — агент не удаляет
            "message": f"journal: {e}"[:120],
        }
    low = journal.lower()
    linked = "link connected" in low
    peers_zero = "current peers count: 0" in low and linked
    last_lines = "\n".join(journal.strip().splitlines()[-8:]).lower()
    recent_fatal = any(
        x in last_lines
        for x in ("status 404", "status 401", "status 403", "invalid_token", "guests cannot")
    )
    healthy = active == "active" and linked and not recent_fatal
    return {
        "ok": True,
        "unit": name,
        "active": active,
        "healthy": healthy,
        "link_connected": linked,
        "peers_zero_ok": peers_zero,
        "recent_fatal": recent_fatal,
        "message": "healthy" if healthy else ("fatal" if recent_fatal else active),
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

    def _authorized(self) -> bool:
        if not INTERNAL_SECRET:
            # Без секрета — только loopback (fail-closed для публичного bind).
            peer = self.client_address[0] if self.client_address else ""
            if peer in ("127.0.0.1", "::1"):
                return True
            log.warning("reject %s: INTERNAL_API_SECRET не задан", peer)
            return False
        got = (self.headers.get("X-Internal-Secret") or "").strip()
        return bool(got) and secrets.compare_digest(got, INTERNAL_SECRET)

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
            if not self._authorized():
                self._send(401, {"ok": False, "message": "unauthorized"})
                return
            self._send(200, _status())
            return
        if path == "/v1/unit-health":
            if not self._authorized():
                self._send(401, {"ok": False, "message": "unauthorized"})
                return
            qs = parse_qs(urlparse(self.path).query)
            unit = (qs.get("unit") or [""])[0]
            self._send(200, _unit_health(unit))
            return
        self._send(404, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(401, {"ok": False, "message": "unauthorized"})
            return
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
        if path == "/v1/units/apply":
            units = body.get("units")
            remove = body.get("remove") or []
            if not isinstance(units, dict) or not isinstance(remove, list):
                self._send(400, {"ok": False, "message": "units{} + remove[] required"})
                return
            try:
                result = _apply_units(units, [str(x) for x in remove])
                self._send(200 if result.get("ok") else 500, result)
            except Exception as e:
                log.exception("units apply failed")
                self._send(500, {"ok": False, "message": str(e)[:300]})
            return
        if path == "/v1/create":
            provider = str(body.get("provider") or "").strip().lower()
            state = body.get("storage_state")
            if not isinstance(state, dict):
                state = None
            headless = bool(body.get("headless", True))
            got = _CREATE_SEM.acquire(timeout=_CREATE_WAIT_SEC)
            if not got:
                self._send(
                    503,
                    {
                        "ok": False,
                        "message": "create busy: другой Playwright ещё работает",
                    },
                )
                return
            try:
                result = asyncio.run(_create(provider, state, headless))
                self._send(200 if result.get("ok") else 502, result)
            except Exception as e:
                log.exception("create failed")
                self._send(500, {"ok": False, "message": str(e)[:300]})
            finally:
                _CREATE_SEM.release()
            return
        self._send(404, {"ok": False, "message": "not found"})


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not INTERNAL_SECRET:
        log.warning(
            "INTERNAL_API_SECRET / OLCRTC_HOST_PROVISION_SECRET пуст — "
            "API кроме /health только с loopback"
        )
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info(
        "listening on %s:%s state_dir=%s auth=%s",
        HOST,
        PORT,
        STATE_DIR,
        "on" if INTERNAL_SECRET else "loopback-only",
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
