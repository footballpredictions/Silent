"""Лёгкая проверка join-hash как у клиента (без TURN / calls.start).

Два объекта:
- хеш звонка (слот БД) — живёт долго;
- anonym_token OK CDN — секунды, не повод менять слот.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

import aiohttp

logger = logging.getLogger(__name__)

KIND_ALIVE = "alive"
KIND_DEAD = "dead"
KIND_SKIP = "skip"
KIND_FLOOD = "flood"

ERROR_OK = 0
ERROR_DEAD = 1
ERROR_PROBE_PENDING = 2

PROBE_BUDGET = 8
PROBE_SLEEP_SEC = 8.0
PROBE_BACKOFF_MINUTES = 20
STALE_HOURS = 6

VK_CONNECT_CLIENT_ID = "8093730"
VK_ANON_API_VERSION = "5.276"
VK_API_HOSTS = ("api.vk.ru", "api.vk.me")

DEAD_MARKERS = (
    "call not found",
    "invalid join link",
    "join link is not valid",
    "conversation not found",
    "хеш мёртв",
)

SETTING_CURSOR = "vk_hash_probe_cursor"
SETTING_LAST = "vk_hash_probe_last"
SETTING_LAST_MSG = "vk_hash_probe_last_message"
SETTING_LAST_ALIVE = "vk_hash_probe_last_alive"
SETTING_LAST_DEAD = "vk_hash_probe_last_dead"
SETTING_LAST_MARKED = "vk_hash_probe_last_marked"
SETTING_PROBE_UNTIL = "vk_hash_probe_until"


def is_call_dead_message(msg: str) -> bool:
    low = (msg or "").lower()
    return any(m in low for m in DEAD_MARKERS)


def is_stale_anonym_token(msg: str) -> bool:
    low = (msg or "").lower()
    return "anonym_token.outdated" in low or (
        "anonym_token" in low and "outdated" in low
    )


def is_flood_message(code: int, msg: str) -> bool:
    if code == 9:
        return True
    low = (msg or "").lower()
    return "flood control" in low or "too many requests" in low


def classify_vk_api_error(code: int, msg: str) -> str:
    """Классификация ответа VK API без сети."""
    if is_flood_message(code, msg):
        return KIND_FLOOD
    if is_stale_anonym_token(msg):
        return KIND_SKIP
    if is_call_dead_message(msg):
        return KIND_DEAD
    low = (msg or "").lower()
    if code == 14 or "captcha" in low:
        return KIND_SKIP
    if code == 10 or "internal" in low:
        return KIND_SKIP
    if "timeout" in low:
        return KIND_SKIP
    return KIND_SKIP


def classify_preview_payload(data: dict[str, Any] | None) -> str:
    if not isinstance(data, dict):
        return KIND_SKIP
    err = data.get("error")
    if isinstance(err, dict):
        code = int(err.get("error_code") or 0)
        msg = str(err.get("error_msg") or "")
        return classify_vk_api_error(code, msg)
    resp = data.get("response")
    if isinstance(resp, dict) and resp.get("user_id") is not None:
        return KIND_ALIVE
    if "response" in data:
        return KIND_ALIVE
    return KIND_SKIP


def apply_probe_kind(state: dict[str, Any], kind: str) -> str:
    """Мутирует last_error_code / is_active / fail_count. Возвращает действие."""
    if kind in (KIND_SKIP, KIND_FLOOD):
        return kind
    if kind == KIND_ALIVE:
        state["last_error_code"] = ERROR_OK
        state["fail_count"] = 0
        state["is_active"] = True
        return "alive"
    prev = int(state.get("last_error_code") or 0)
    state["fail_count"] = int(state.get("fail_count") or 0) + 1
    if prev in (ERROR_PROBE_PENDING, ERROR_DEAD):
        state["last_error_code"] = ERROR_DEAD
        state["is_active"] = False
        return "deactivated"
    state["last_error_code"] = ERROR_PROBE_PENDING
    return "pending"


def probe_priority(hash_row: Any, now: datetime | None = None) -> tuple[int, str]:
    now = now or datetime.utcnow()
    err = int(getattr(hash_row, "last_error_code", 0) or 0)
    fails = int(getattr(hash_row, "fail_count", 0) or 0)
    checked = getattr(hash_row, "last_checked", None)
    if err == ERROR_PROBE_PENDING:
        pri = 0
    elif fails > 0:
        pri = 1
    elif checked is None:
        pri = 2
    else:
        age = now - checked.replace(tzinfo=None) if getattr(checked, "tzinfo", None) else now - checked
        pri = 2 if age >= timedelta(hours=STALE_HOURS) else 3
    return (pri, str(getattr(hash_row, "id", "")))


def select_probe_batch(rows: list[Any], cursor: str | None, budget: int = PROBE_BUDGET) -> list[Any]:
    if not rows or budget <= 0:
        return []
    ranked = sorted(rows, key=lambda h: probe_priority(h))
    pending = [h for h in ranked if int(getattr(h, "last_error_code", 0) or 0) == ERROR_PROBE_PENDING]
    rest = [h for h in ranked if h not in pending]
    if cursor:
        idx = next((i for i, h in enumerate(rest) if str(h.id) == cursor), -1)
        if idx >= 0:
            rest = rest[idx + 1 :] + rest[: idx + 1]
    out: list[Any] = []
    seen: set[str] = set()
    for h in pending + rest:
        hid = str(h.id)
        if hid in seen:
            continue
        seen.add(hid)
        out.append(h)
        if len(out) >= budget:
            break
    return out


def _vk_error_from(data: dict[str, Any] | None) -> tuple[int, str]:
    if not isinstance(data, dict):
        return 0, ""
    err = data.get("error")
    if not isinstance(err, dict):
        return 0, ""
    return int(err.get("error_code") or 0), str(err.get("error_msg") or "")


def _extract_anonym_token(data: dict[str, Any] | None) -> str | None:
    if not isinstance(data, dict):
        return None
    resp = data.get("response")
    if isinstance(resp, dict):
        tok = resp.get("token")
        if tok:
            return str(tok)
    tok = data.get("token") or data.get("access_token")
    return str(tok) if tok else None


class JoinHashProber:
    """Один anonym token на пачку хешей; TURN не трогаем."""

    def __init__(self, session: aiohttp.ClientSession):
        self._session = session
        self._token: str | None = None
        self._device_id = str(uuid.uuid4())
        self._name = "SilentProbe"
        self.flood = False

    async def _post(self, url: str) -> dict[str, Any]:
        async with self._session.post(url, data=b"", timeout=aiohttp.ClientTimeout(total=12)) as resp:
            data = await resp.json(content_type=None)
            return data if isinstance(data, dict) else {}

    async def _refresh_anonym_token(self) -> str:
        link = quote("https://vk.ru/call/join/probe", safe="")
        last: dict[str, Any] = {}
        for host in VK_API_HOSTS:
            url = (
                f"https://{host}/method/auth.getAnonymToken?v={VK_ANON_API_VERSION}"
                f"&client_id={VK_CONNECT_CLIENT_ID}&link={link}"
                f"&device_id={self._device_id}&anonymName={quote(self._name)}"
                f"&lang=en"
            )
            try:
                last = await self._post(url)
            except Exception as e:
                logger.debug("getAnonymToken %s: %s", host, e)
                continue
            code, msg = _vk_error_from(last)
            if is_flood_message(code, msg):
                self.flood = True
                raise RuntimeError("vk flood")
            tok = _extract_anonym_token(last)
            if tok:
                self._token = tok
                return tok
        raise RuntimeError("no anonym token")

    async def probe(self, hash_val: str) -> str:
        hv = (hash_val or "").strip()
        if len(hv) < 6:
            return KIND_SKIP
        link = quote(f"https://vk.ru/call/join/{hv}", safe="")
        for attempt in range(2):
            if self.flood:
                return KIND_FLOOD
            try:
                if not self._token:
                    await self._refresh_anonym_token()
            except RuntimeError:
                return KIND_FLOOD if self.flood else KIND_SKIP
            except Exception:
                return KIND_SKIP

            last: dict[str, Any] = {}
            for host in VK_API_HOSTS:
                url = (
                    f"https://{host}/method/messages.getCallPreview"
                    f"?v={VK_ANON_API_VERSION}&anonymous_token={quote(self._token or '')}"
                    f"&device_id={self._device_id}&extended=1"
                    f"&fields=first_name&lang=en&link={link}"
                )
                try:
                    last = await self._post(url)
                    break
                except Exception as e:
                    logger.debug("getCallPreview %s: %s", host, e)
                    last = {}
            if not last:
                return KIND_SKIP

            kind = classify_preview_payload(last)
            code, msg = _vk_error_from(last)
            if is_stale_anonym_token(msg) and attempt == 0:
                self._token = None
                continue
            if kind == KIND_FLOOD:
                self.flood = True
            return kind
        return KIND_SKIP
