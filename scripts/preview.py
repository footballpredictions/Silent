#!/usr/bin/env python3
"""Local preview of the OpenWrt Silent web UI (no router required)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT))

from lib.silent_lan import lan_url  # noqa: E402
from lib.silent_servers import display_vpn_servers, normalize_slot, selected_title  # noqa: E402
from lib.silent_theme import palette  # noqa: E402

HOST = os.environ.get("SILENT_PREVIEW_HOST", "127.0.0.1")
PORT = int(os.environ.get("SILENT_PREVIEW_PORT", "7788"))
LAN_IP = os.environ.get("SILENT_PREVIEW_LAN", "192.168.1.1")
HIVE = os.environ.get("SILENT_HIVE", "https://132-243-234-162.nip.io").rstrip("/")
PUBLIC_THEME = f"{HIVE}/api/vpn/theme"
PREVIEW_MOCK = os.environ.get("SILENT_PREVIEW_MOCK", "") == "1"
BOOTSTRAP = "4uhJXsVypBdlEbvt6k4hPEFi3RooXUqyUwDG4lgPBDY"
APP_VERSION = "1.0.165"

_theme_lock = threading.Lock()
_theme_cache: dict | None = None
_session: dict | None = None
_connected = False
_selected = "server1"
_dns_preset = "server"
_dns_custom = ""
_ru_direct = False
_hive_profile: dict | None = None
ROUTER_NAME = os.environ.get("SILENT_PREVIEW_ROUTER", "Xiaomi AX3000T")


def _fp(email: str) -> str:
    return hashlib.md5(f"openwrt-preview:{email}".encode("utf-8")).hexdigest()


def hive(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{HIVE}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-App-Version", APP_VERSION)
    req.add_header("User-Agent", "SilentOpenWrtPreview/1.0")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"detail": raw or exc.reason}
        if not isinstance(payload, dict):
            payload = {"detail": payload}
        return exc.code, payload
    except Exception:
        return 502, {"detail": "Улей недоступен"}


def hive_token() -> str:
    return str((_session or {}).get("access_token") or "")


def live_profile() -> dict | None:
    global _hive_profile
    token = hive_token()
    if not token or token == "preview":
        return _hive_profile
    code, data = hive("GET", "/api/users/me", token=token)
    if code == 200 and isinstance(data, dict):
        _hive_profile = data
        return data
    return _hive_profile


def live_servers() -> dict:
    email = str((_session or {}).get("email") or "preview")
    token = hive_token()
    if token and token != "preview":
        code, data = hive(
            "GET",
            f"/api/vpn/servers?fingerprint={_fp(email)}&app_version={APP_VERSION}",
            token=token,
        )
        if code == 200 and isinstance(data, dict):
            servers = display_vpn_servers(data.get("servers") or [])
            selected = normalize_slot(str(data.get("selected_server") or _selected)) or _selected
            return {
                "selected_server": selected,
                "selected_title": selected_title(selected, servers),
                "servers": servers,
            }
    return mock_servers()


def register_preview_device(email: str, token: str) -> None:
    hive(
        "POST",
        "/api/vpn/device/register",
        {
            "device_name": f"OpenWrt {ROUTER_NAME}"[:64],
            "device_type": "pc",
            "device_fingerprint": _fp(email),
            "bootstrap_hash": BOOTSTRAP,
        },
        token=token,
    )


def load_theme() -> dict:
    global _theme_cache
    with _theme_lock:
        if _theme_cache is not None:
            return _theme_cache
    try:
        req = urllib.request.Request(PUBLIC_THEME, headers={"User-Agent": "SilentOpenWrtPreview/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        with _theme_lock:
            _theme_cache = data
        return data
    except Exception:
        fallback = {
            "primary_color": "#000000",
            "background_color": "#FFFFFF",
            "text_color": "#000000",
            "font_family": "Inter",
            "app_name": "Silent VPN",
            "login_link_color": "#4680C2",
            "logo_url": "/static/logo.png",
            "home_bg_image_url": "/static/theme/home_bg.webp",
            "telegram_channel_url": "https://t.me/silentvpn3",
            "support_url": "https://t.me/silentvpn3?direct",
            "menu_bonuses_label": "Бонусы",
            "bonuses_title": "Бонусы",
            "bonuses_intro_text": (
                "Рефералка: отправьте другу ссылку или код. Он регистрируется по ним и оплачивает любую подписку — "
                "оба получаете +30 дней."
            ),
            "bonuses_referral_title": "Ваша ссылка",
            "bonuses_referral_hint": "Скопируйте и отправьте другу",
            "bonuses_promo_title": "Промокод",
            "bonuses_promo_hint": "Проверить скидку к тарифу",
            "login_remember_me_label": "Запомнить меня",
            "login_forgot_password_label": "Забыли пароль?",
        }
        with _theme_lock:
            _theme_cache = fallback
        return fallback


def mock_profile(email: str) -> dict:
    return {
        "email": email,
        "display_id": "S27-RTR",
        "subscription": {
            "is_active": True,
            "plan_type": "trial",
            "expires_at": "2026-09-15T00:00:00+00:00",
            "days_left": 3,
        },
        "devices_count": 2,
        "max_devices": 3,
        "devices": [
            {
                "id": "router-1",
                "device_name": f"OpenWrt {ROUTER_NAME}",
                "device_type": "pc",
                "platform": "openwrt",
                "router_name": ROUTER_NAME,
                "is_connected": _connected,
                "self": True,
            },
            {
                "id": "phone-1",
                "device_name": "Android",
                "device_type": "android",
                "is_connected": False,
                "self": False,
            },
        ],
    }


def mock_servers() -> dict:
    api = [
        {"key": "server1", "title": "Сервер 1", "public_ip": "132.243.234.162"},
        {"key": "server2", "title": "Сервер 2", "public_ip": "87.58.213.193"},
        {"key": "server3", "title": "Сервер 3", "public_ip": "78.17.74.27"},
        {"key": "server4", "title": "Сервер 4 для ИИ", "public_ip": ""},
    ]
    servers = display_vpn_servers(api)
    return {
        "selected_server": _selected,
        "selected_title": selected_title(_selected, servers),
        "servers": servers,
    }


def read_json(handler: SimpleHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def write_json(handler: SimpleHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


class PreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path in ("/", "/index.html"):
            return self._index()
        if parsed.path.startswith("/silent/api/"):
            return self._api("GET", parsed)
        if parsed.path.startswith("/silent-vpn/"):
            self.path = parsed.path[len("/silent-vpn") :] or "/"
            return self._static()
        if parsed.path.endswith((".css", ".js")):
            return self._static()
        return SimpleHTTPRequestHandler.do_GET(self)

    def _static(self):
        path = urlparse(self.path).path
        rel = path.lstrip("/")
        file_path = (WEB / rel).resolve()
        if not str(file_path).startswith(str(WEB.resolve())) or not file_path.is_file():
            self.send_error(404)
            return
        data = file_path.read_bytes()
        ctype = "text/css" if file_path.suffix == ".css" else (
            "text/javascript" if file_path.suffix == ".js" else "application/octet-stream"
        )
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/silent/api/"):
            return self._api("POST", parsed)
        self.send_error(404)

    def _index(self) -> None:
        html = (WEB / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html)

    def _api(self, method: str, parsed) -> None:
        global _session, _connected, _selected, _dns_preset, _dns_custom, _ru_direct, _hive_profile
        op = parsed.path[len("/silent/api/") :].strip("/")
        qs = parse_qs(parsed.query)
        lan_ip = (qs.get("lan") or [LAN_IP])[0]
        theme = load_theme()
        live = bool(_session and hive_token() not in ("", "preview"))
        slots = live_servers() if live else mock_servers()
        base = {
            "lan_ip": lan_ip,
            "lan_url": lan_url(lan_ip),
            "router_name": ROUTER_NAME,
            "theme": theme,
            "palette": palette(theme, "light"),
            "dns_preset": _dns_preset,
            "dns_custom": _dns_custom,
            "ru_direct": _ru_direct,
            "live": live,
            "preview": True,
            **slots,
        }

        if op == "theme" and method == "GET":
            return write_json(self, theme)
        if op == "status" and method == "GET":
            payload = {**base, "connected": _connected}
            if _session:
                payload["session"] = {k: _session[k] for k in ("email",) if k in _session}
                payload["profile"] = live_profile() if live else mock_profile(_session["email"])
            return write_json(self, payload)
        if op == "login" and method == "POST":
            body = read_json(self)
            email = str(body.get("email") or "").strip()
            password = str(body.get("password") or "")
            if "@" not in email or len(password) < 8:
                return write_json(self, {"detail": "Неверный email или пароль (минимум 8 символов)"}, 400)
            if not PREVIEW_MOCK:
                code, data = hive("POST", "/api/auth/login", {"email": email, "password": password})
                token = str(data.get("access_token") or "")
                if code != 200 or not token:
                    return write_json(self, data if data else {"detail": "Неверный email или пароль"}, code or 400)
                _session = {"email": email, "access_token": token}
                register_preview_device(email, token)
                _hive_profile = live_profile()
                return write_json(self, {
                    **base,
                    "live": True,
                    "email": email,
                    "profile": _hive_profile or data.get("user") or {},
                    "connected": _connected,
                    **live_servers(),
                })
            _session = {"email": email, "access_token": "preview"}
            _hive_profile = None
            return write_json(self, {
                **base,
                "live": False,
                "email": email,
                "profile": mock_profile(email),
                "connected": _connected,
            })
        if op == "register" and method == "POST":
            body = read_json(self)
            if PREVIEW_MOCK:
                if "@" not in str(body.get("email") or "") or len(str(body.get("password") or "")) < 8:
                    return write_json(self, {"detail": "Укажите email и пароль от 8 символов"}, 400)
                return write_json(self, {"ok": True})
            code, data = hive("POST", "/api/auth/register", body)
            return write_json(self, data, code)
        if op == "forgot" and method == "POST":
            body = read_json(self)
            if PREVIEW_MOCK:
                return write_json(self, {"ok": True})
            code, data = hive("POST", "/api/auth/forgot-password", {"email": body.get("email")})
            return write_json(self, data, code)
        if op == "logout" and method == "POST":
            _session = None
            _connected = False
            _hive_profile = None
            return write_json(self, {"ok": True})
        if op == "connect" and method == "POST":
            _connected = True
            return write_json(self, {"ok": True, "connected": True})
        if op == "disconnect" and method == "POST":
            _connected = False
            return write_json(self, {"ok": True, "connected": False})
        if op == "profile" and method == "GET":
            if live:
                me = live_profile()
                return write_json(self, me or {"detail": "Нет профиля"}, 200 if me else 401)
            email = (_session or {}).get("email") or "preview@silent.vpn"
            return write_json(self, mock_profile(email))
        if op == "servers" and method == "GET":
            return write_json(self, live_servers() if live else mock_servers())
        if op == "server" and method == "POST":
            body = read_json(self)
            key = normalize_slot(str(body.get("key") or _selected)) or _selected
            _selected = key
            if live:
                email = str((_session or {}).get("email") or "")
                code, data = hive(
                    "POST",
                    "/api/vpn/servers/select",
                    {
                        "device_fingerprint": _fp(email),
                        "preferred_server": key,
                        "app_version": APP_VERSION,
                    },
                    token=hive_token(),
                )
                if code == 200 and isinstance(data, dict):
                    servers = display_vpn_servers(data.get("servers") or [])
                    selected = normalize_slot(str(data.get("selected_server") or key)) or key
                    _selected = selected
                    return write_json(self, {
                        "selected_server": selected,
                        "selected_title": selected_title(selected, servers),
                        "servers": servers,
                    })
            return write_json(self, mock_servers())
        if op == "dns" and method == "GET":
            return write_json(self, {"preset": _dns_preset, "custom": _dns_custom})
        if op == "dns" and method == "POST":
            body = read_json(self)
            _dns_preset = str(body.get("preset") or "server")
            _dns_custom = str(body.get("custom") or "")
            return write_json(self, {"preset": _dns_preset, "custom": _dns_custom})
        if op == "exclusions" and method == "GET":
            return write_json(self, {"ru_direct": _ru_direct})
        if op == "exclusions" and method == "POST":
            body = read_json(self)
            _ru_direct = bool(body.get("ru_direct"))
            return write_json(self, {"ru_direct": _ru_direct})
        if op == "referral" and method == "GET":
            if live:
                code, data = hive("GET", "/api/users/me/referral", token=hive_token())
                return write_json(self, data, code)
            return write_json(self, {
                "referral_link": "https://silentvpn3.github.io/?ref=S27RTR",
                "referral_code": "S27RTR",
                "invited_count": 2,
                "rewarded_count": 1,
            })
        if op == "promo" and method == "POST":
            body = read_json(self)
            promo = str(body.get("code") or "").strip()
            if live:
                code, data = hive("POST", "/api/payments/promo/check", {"code": promo}, token=hive_token())
                return write_json(self, data, code)
            if not promo:
                return write_json(self, {"detail": "Не найден"}, 404)
            return write_json(self, {"discount_percent": 20})
        if op == "pay" and method == "POST":
            body = read_json(self)
            if live:
                code, data = hive(
                    "POST",
                    "/api/payments/init",
                    {"plan_type": body.get("plan_type") or "monthly"},
                    token=hive_token(),
                )
                return write_json(self, data, code)
            return write_json(self, {"url": "https://yoomoney.ru", "label": "silent_preview"})
        return write_json(self, {"detail": "unknown op"}, 404)


def main() -> None:
    load_theme()
    server = ThreadingHTTPServer((HOST, PORT), PreviewHandler)
    url = f"http://{HOST}:{PORT}/"
    print(f"Silent OpenWrt UI preview: {url}", flush=True)
    print(f"Router URL (as on device): {lan_url(LAN_IP)}", flush=True)
    if PREVIEW_MOCK:
        print("Login: MOCK (SILENT_PREVIEW_MOCK=1). Any email + password 8+.", flush=True)
    else:
        print(f"Login: live hive {HIVE} — real admin/user accounts.", flush=True)
    print("Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
