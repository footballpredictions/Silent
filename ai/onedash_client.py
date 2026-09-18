"""OneDash API 2.0: инвентарь VPS и dry-run смены IP.

Документация: https://github.com/OneDashRDP/api-docs
Base: https://api.rdp-onedash.ru  Authorization: Bearer <key>

В публичном API 2.0 нет метода смены IP (есть power/ptr/reinstall/delete).
Платный POST не вызывается: нет пути в доках, дефолт dry-run, executed=False.
Ключ не логируется.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode

API_BASE_DEFAULT = "https://api.rdp-onedash.ru"
V1_BASE_DEFAULT = "https://rdp-onedash.ru/web-api"
HOSTER_ID = "onedash"

# Пути, которые кабинет мог бы использовать для смены IP. Только GET-probe.
CHANGE_IP_GET_PROBES = (
    "/api/vps/{id}/ip",
    "/api/vps/{id}/change-ip",
    "/api/vps/{id}/refresh-ip",
    "/api/vps/{id}/network",
)

# Методы, которые списывают деньги / ломают машину — клиент их не зовёт.
FORBIDDEN_POST_SUFFIXES = (
    "/create",
    "/clone",
    "/reinstall",
    "/delete",
    "/power",
    "/password",
    "/credentials",
)

HttpFn = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, str]]


def _redact(text: str) -> str:
    key = (os.environ.get("ONEDASH_API_KEY") or "").strip()
    if key and key in text:
        return text.replace(key, "***")
    return text


def _default_http(
    url: str,
    method: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float,
) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in headers.items():
        if k.lower() == "authorization":
            req.add_header(k, v)
        else:
            req.add_header(k, v)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return int(resp.status), raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace") if e.fp else ""
        return int(e.code), raw
    except Exception as e:
        return 0, _redact(str(e))


@dataclass(frozen=True)
class VpsItem:
    vps_id: int
    name: str
    ip: str
    active: bool
    location: str = ""
    os: str = ""
    order_id: int | None = None
    static_ip: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "vps_id": self.vps_id,
            "name": self.name,
            "ip": self.ip,
            "active": self.active,
            "location": self.location,
            "os": self.os,
            "order_id": self.order_id,
            "static_ip": self.static_ip,
        }


@dataclass
class Inventory:
    ok: bool
    reason: str = ""
    auth_ok: bool = False
    health_ok: bool = False
    balance_known: bool = False
    currency: str = ""
    items: list[VpsItem] = field(default_factory=list)
    http_status: dict[str, int] = field(default_factory=dict)

    def find_by_ip(self, ip: str) -> VpsItem | None:
        want = (ip or "").strip()
        for item in self.items:
            if item.ip == want:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "auth_ok": self.auth_ok,
            "health_ok": self.health_ok,
            "balance_known": self.balance_known,
            "currency": self.currency,
            "items": [i.to_dict() for i in self.items],
            "http_status": dict(self.http_status),
        }


@dataclass
class ChangeIpPlan:
    executed: bool = False
    dry_run: bool = True
    reason: str = ""
    hoster_id: str = HOSTER_ID
    vps_id: int | None = None
    current_ip: str = ""
    would_call: str = ""
    probe: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "executed": False,
            "dry_run": True,
            "reason": self.reason,
            "hoster_id": self.hoster_id,
            "vps_id": self.vps_id,
            "current_ip": self.current_ip,
            "would_call": self.would_call,
            "probe": dict(self.probe),
            "notes": list(self.notes),
        }


def parse_vps_items(payload: Any) -> list[VpsItem]:
    """Разбор GET /api/vps без требования живого HTTP."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        items = data.get("items")
    elif isinstance(payload, dict):
        items = payload.get("items")
    else:
        items = None
    if not isinstance(items, list):
        return []
    out: list[VpsItem] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        conn = raw.get("connection") if isinstance(raw.get("connection"), dict) else {}
        host = str(conn.get("host") or raw.get("ip") or raw.get("host") or "").strip()
        opts = raw.get("options") if isinstance(raw.get("options"), dict) else {}
        static_ip = opts.get("static_ip")
        vps_id = raw.get("id") or raw.get("vps_id")
        try:
            vid = int(vps_id)
        except (TypeError, ValueError):
            continue
        order_id = raw.get("order_id")
        try:
            oid = int(order_id) if order_id is not None else None
        except (TypeError, ValueError):
            oid = None
        out.append(
            VpsItem(
                vps_id=vid,
                name=str(raw.get("name") or ""),
                ip=host,
                active=bool(raw.get("active", True)),
                location=str(raw.get("location") or ""),
                os=str(raw.get("os") or ""),
                order_id=oid,
                static_ip=bool(static_ip) if static_ip is not None else None,
            )
        )
    return out


def parse_balance_known(payload: Any) -> tuple[bool, str]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return False, ""
    if "balance" not in data:
        return False, ""
    return True, str(data.get("currency") or "")


class OneDashClient:
    def __init__(
        self,
        *,
        api_key: str = "",
        api_base: str = "",
        timeout: float = 20.0,
        http: HttpFn | None = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("ONEDASH_API_KEY") or "").strip()
        self.api_base = (api_base or os.environ.get("ONEDASH_API_BASE") or API_BASE_DEFAULT).rstrip("/")
        self.timeout = timeout
        self._http = http or _default_http

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def request(self, method: str, path: str, *, body: dict | None = None) -> tuple[int, Any]:
        method_u = method.upper()
        if method_u not in ("GET", "HEAD"):
            raise RuntimeError(f"onedash: {method_u} запрещён в этом клиенте")
        lower = path.lower()
        for suffix in FORBIDDEN_POST_SUFFIXES:
            if lower.endswith(suffix) and method_u != "GET":
                raise RuntimeError(f"onedash: запрещённый путь {path}")
        url = path if path.startswith("http") else f"{self.api_base}{path}"
        raw_body = json.dumps(body).encode("utf-8") if body is not None else None
        headers = self._headers()
        if raw_body is not None:
            headers["Content-Type"] = "application/json"
        status, text = self._http(url, method_u, headers, raw_body, self.timeout)
        parsed: Any = text
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = {"raw": _redact(text)[:500]}
        return status, parsed

    def get(self, path: str) -> tuple[int, Any]:
        return self.request("GET", path)

    def v1_get(self, method_name: str) -> tuple[int, Any]:
        """Старый web-api: GET /web-api/{method} + заголовок Api-Key. Только чтение."""
        name = method_name.strip().lstrip("/")
        banned = ("create", "delete", "reinstall", "power", "password", "clone")
        if not name or "/" in name or any(x in name.lower() for x in banned):
            raise RuntimeError("onedash v1: недопустимый method")
        base = (os.environ.get("ONEDASH_V1_BASE") or V1_BASE_DEFAULT).rstrip("/")
        url = f"{base}/{name}"
        headers = {"Accept": "application/json", "Api-Key": self.api_key}
        status, text = self._http(url, "GET", headers, None, self.timeout)
        parsed: Any = text
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = {"raw": _redact(text)[:500]}
        return status, parsed

    def health(self) -> tuple[int, Any]:
        return self.get("/health")

    def auth_check(self) -> tuple[int, Any]:
        return self.get("/api/auth/check")

    def balance(self) -> tuple[int, Any]:
        return self.get("/api/balance")

    def list_vps(self, page: int = 1, per_page: int = 100) -> tuple[int, Any]:
        qs = urlencode({"page": page, "per_page": per_page})
        return self.get(f"/api/vps?{qs}")

    def probe_change_ip_paths(self, vps_id: int) -> dict[str, int]:
        """Только GET: 404 нет метода, 405 возможно POST, 200 чтение IP."""
        out: dict[str, int] = {}
        for tmpl in CHANGE_IP_GET_PROBES:
            path = tmpl.format(id=vps_id)
            status, _ = self.get(path)
            out[path] = status
        return out

    def inventory(self) -> Inventory:
        if not self.api_key:
            return Inventory(ok=False, reason="api_key_missing")
        http_status: dict[str, int] = {}
        health_status, _ = self.health()
        http_status["/health"] = health_status
        auth_status, _ = self.auth_check()
        http_status["/api/auth/check"] = auth_status
        auth_ok = auth_status == 200
        bal_status, bal_payload = self.balance()
        http_status["/api/balance"] = bal_status
        balance_known, currency = parse_balance_known(bal_payload) if bal_status == 200 else (False, "")
        vps_status, vps_payload = self.list_vps()
        http_status["/api/vps"] = vps_status
        items = parse_vps_items(vps_payload) if vps_status == 200 else []
        if not auth_ok:
            return Inventory(
                ok=False,
                reason="auth_failed",
                auth_ok=False,
                health_ok=health_status == 200,
                http_status=http_status,
            )
        return Inventory(
            ok=True,
            reason="ok",
            auth_ok=True,
            health_ok=health_status == 200,
            balance_known=balance_known,
            currency=currency,
            items=items,
            http_status=http_status,
        )

    def plan_change_ip(
        self,
        current_ip: str,
        *,
        dry_run: bool = True,
        paid_enabled: bool = False,
        confirm: bool = False,
        inventory: Inventory | None = None,
    ) -> ChangeIpPlan:
        """Никогда не делает POST. Путь смены IP в API 2.0 не документирован."""
        inv = inventory if inventory is not None else self.inventory()
        item = inv.find_by_ip(current_ip)
        configured = (os.environ.get("ONEDASH_CHANGE_IP_PATH") or "").strip()
        plan = ChangeIpPlan(
            executed=False,
            dry_run=True,
            current_ip=current_ip,
            vps_id=item.vps_id if item else None,
        )
        if not inv.ok:
            plan.reason = inv.reason or "inventory_failed"
            return plan
        if item is None:
            plan.reason = "vps_not_in_account"
            return plan
        if item.static_ip is False:
            plan.notes.append("option_static_ip=false")
        probe = self.probe_change_ip_paths(item.vps_id)
        plan.probe = probe
        if not configured:
            plan.reason = "change_ip_not_in_api_docs"
            plan.would_call = ""
            return plan
        plan.would_call = f"POST {configured}"
        if dry_run or not paid_enabled or not confirm:
            plan.reason = "dry_run"
            return plan
        plan.reason = "paid_blocked_in_code"
        return plan


def load_key_from_env_file(path: str) -> None:
    """Читает .env.deploy без печати значений. Не перезаписывает уже заданные env."""
    p = os.path.expandvars(os.path.expanduser(path))
    if not os.path.isfile(p):
        return
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
