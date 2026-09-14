"""QR-вход: одноразовые сессии (ТВ ждёт) и короткий код пользователя.

Пароль в QR не кладём. Старые клиенты эндпоинты не вызывают.
Хранилище — Redis (несколько uvicorn workers); MemoryQrStore для тестов.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

KIND_SESSION = "s"
KIND_USER = "u"
QR_SCHEME_HOST = "silentvpn://qr"
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")

SESSION_TTL_SEC = 120
USER_CODE_TTL_SEC = 120


class QrLoginError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class QrPayload:
    kind: str
    code: str


@dataclass(frozen=True)
class QrSessionStart:
    token: str
    expires_in: int
    payload: str


@dataclass(frozen=True)
class QrPoll:
    status: str  # pending | approved | expired
    user_id: str | None = None
    device: dict[str, Any] | None = None


@dataclass(frozen=True)
class QrUserCode:
    code: str
    expires_in: int
    payload: str


def build_qr_payload(kind: str, code: str) -> str:
    return f"{QR_SCHEME_HOST}?k={kind}&c={code}"


def parse_qr_payload(raw: str | None) -> QrPayload | None:
    text = (raw or "").strip()
    if not text:
        return None
    lower = text.lower()
    silent_at = lower.find(QR_SCHEME_HOST)
    if silent_at >= 0:
        text = text[silent_at:].split()[0]
    else:
        marker = lower.find("/qr?")
        if marker < 0:
            return None
        http_at = lower.rfind("http", 0, marker + 1)
        text = text[http_at if http_at >= 0 else marker :].split()[0]
    parsed = urlparse(text)
    if parsed.scheme == "silentvpn":
        if parsed.netloc != "qr":
            return None
    elif parsed.scheme in ("http", "https"):
        if not parsed.path.rstrip("/").endswith("/qr"):
            return None
    else:
        return None
    qs = parse_qs(parsed.query, keep_blank_values=False)
    kind = (qs.get("k") or [""])[0].strip()
    code = (qs.get("c") or [""])[0].strip()
    if kind not in (KIND_SESSION, KIND_USER):
        return None
    if not _CODE_RE.match(code):
        return None
    return QrPayload(kind=kind, code=code)


class QrStore(Protocol):
    async def put(self, key: str, value: dict[str, Any], ttl_sec: int) -> None: ...
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def delete(self, key: str) -> None: ...
    async def ttl(self, key: str) -> int | None: ...


class MemoryQrStore:
    """Процесс-локальное хранилище. Только тесты / один воркер."""

    def __init__(self, clock: Callable[[], float] | None = None):
        self._clock = clock or time.time
        self._data: dict[str, tuple[float, dict[str, Any]]] = {}

    async def put(self, key: str, value: dict[str, Any], ttl_sec: int) -> None:
        self._data[key] = (self._clock() + max(1, int(ttl_sec)), dict(value))

    async def get(self, key: str) -> dict[str, Any] | None:
        item = self._data.get(key)
        if not item:
            return None
        exp, val = item
        if self._clock() >= exp:
            self._data.pop(key, None)
            return None
        return dict(val)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def ttl(self, key: str) -> int | None:
        item = self._data.get(key)
        if not item:
            return None
        left = int(item[0] - self._clock())
        if left <= 0:
            self._data.pop(key, None)
            return None
        return left


class RedisQrStore:
    def __init__(self, redis_client: Any):
        self._redis = redis_client

    @classmethod
    def from_settings(cls) -> "RedisQrStore":
        from redis import asyncio as aioredis
        from app.config import settings

        return cls(aioredis.from_url(settings.REDIS_URL, decode_responses=True))

    async def put(self, key: str, value: dict[str, Any], ttl_sec: int) -> None:
        await self._redis.set(key, json.dumps(value, separators=(",", ":")), ex=max(1, int(ttl_sec)))

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._redis.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def ttl(self, key: str) -> int | None:
        left = await self._redis.ttl(key)
        if left is None or int(left) < 0:
            return None
        return int(left)


def _session_key(token: str) -> str:
    return f"qr:s:{token}"


def _user_code_key(code: str) -> str:
    return f"qr:u:{code}"


def _user_ptr_key(user_id: str) -> str:
    return f"qr:uid:{user_id}"


class QrLoginService:
    def __init__(
        self,
        store: QrStore,
        *,
        session_ttl: int = SESSION_TTL_SEC,
        user_code_ttl: int = USER_CODE_TTL_SEC,
        clock: Callable[[], float] | None = None,
    ):
        self._store = store
        self._session_ttl = session_ttl
        self._user_code_ttl = user_code_ttl
        self._clock = clock or time.time

    async def start_session(self, device: dict[str, Any] | None = None) -> QrSessionStart:
        token = secrets.token_urlsafe(24)
        payload = {
            "status": "pending",
            "device": device or None,
        }
        await self._store.put(_session_key(token), payload, self._session_ttl)
        return QrSessionStart(
            token=token,
            expires_in=self._session_ttl,
            payload=build_qr_payload(KIND_SESSION, token),
        )

    async def poll_session(self, token: str) -> QrPoll:
        if not _CODE_RE.match(token or ""):
            return QrPoll(status="expired")
        key = _session_key(token)
        data = await self._store.get(key)
        if not data:
            return QrPoll(status="expired")
        status = data.get("status")
        if status == "pending":
            return QrPoll(status="pending")
        if status == "approved":
            user_id = str(data.get("user_id") or "")
            device = data.get("device") if isinstance(data.get("device"), dict) else None
            if not user_id:
                return QrPoll(status="expired")
            return QrPoll(status="approved", user_id=user_id, device=device)
        return QrPoll(status="expired")

    async def session_device(self, token: str) -> dict[str, Any] | None:
        data = await self._store.get(_session_key(token))
        if not data:
            return None
        device = data.get("device")
        return device if isinstance(device, dict) else None

    async def approve_session(self, user_id: str, token: str) -> None:
        if not _CODE_RE.match(token or ""):
            raise QrLoginError("not_found", "Код недействителен или уже использован")
        key = _session_key(token)
        data = await self._store.get(key)
        if not data:
            raise QrLoginError("expired", "Код истёк или не найден")
        if data.get("status") != "pending":
            raise QrLoginError("already_used", "Этот QR уже подтверждён")
        ttl = await self._store.ttl(key)
        if ttl is None:
            raise QrLoginError("expired", "Код истёк или не найден")
        data["status"] = "approved"
        data["user_id"] = str(user_id)
        await self._store.put(key, data, ttl)

    async def issue_user_code(self, user_id: str) -> QrUserCode:
        uid = str(user_id)
        ptr_key = _user_ptr_key(uid)
        old = await self._store.get(ptr_key)
        if old and old.get("code"):
            await self._store.delete(_user_code_key(str(old["code"])))
        code = secrets.token_urlsafe(24)
        await self._store.put(_user_code_key(code), {"user_id": uid}, self._user_code_ttl)
        await self._store.put(ptr_key, {"code": code}, self._user_code_ttl)
        return QrUserCode(
            code=code,
            expires_in=self._user_code_ttl,
            payload=build_qr_payload(KIND_USER, code),
        )

    async def redeem_user_code(self, code: str) -> str:
        if not _CODE_RE.match(code or ""):
            raise QrLoginError("not_found", "Код недействителен или уже использован")
        key = _user_code_key(code)
        data = await self._store.get(key)
        if not data:
            raise QrLoginError("not_found", "Код недействителен или уже использован")
        user_id = str(data.get("user_id") or "")
        await self._store.delete(key)
        if not user_id:
            raise QrLoginError("not_found", "Код недействителен или уже использован")
        ptr = await self._store.get(_user_ptr_key(user_id))
        if ptr and ptr.get("code") == code:
            await self._store.delete(_user_ptr_key(user_id))
        return user_id

    async def approve_payload(self, user_id: str, raw: str) -> None:
        parsed = parse_qr_payload(raw)
        if not parsed or parsed.kind != KIND_SESSION:
            raise QrLoginError("invalid", "Это не QR для подтверждения входа")
        await self.approve_session(user_id, parsed.code)

    async def redeem_payload(self, raw: str) -> str:
        parsed = parse_qr_payload(raw)
        if not parsed or parsed.kind != KIND_USER:
            raise QrLoginError("invalid", "Это не QR пользователя")
        return await self.redeem_user_code(parsed.code)


_service: QrLoginService | None = None


def get_qr_login_service() -> QrLoginService:
    global _service
    if _service is None:
        _service = QrLoginService(RedisQrStore.from_settings())
    return _service
