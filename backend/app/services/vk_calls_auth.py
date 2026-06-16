"""VK Звонки (calls.vk.com) — silent_token → access_token для calls.start."""
from __future__ import annotations

import json
import logging
import secrets
import uuid as uuid_lib
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

import aiohttp

from app.config import settings
from app.services.vk_agent_auth import VK_API_VERSION, VK_USER_AGENT

logger = logging.getLogger(__name__)

VK_CALLS_APP_ID = 7793118
VK_CALLS_REDIRECT_URI = "vkcau://vk.com/auth"
VK_CALLS_AUTH_VERSION = "0.0.2"


def format_calls_uuid(raw: str | None = None) -> str:
    """VK Calls ожидает uuid в фигурных скобках: {uuid4}."""
    if raw:
        s = raw.strip()
        if s.startswith("{") and s.endswith("}"):
            return s
        return f"{{{s}}}"
    return f"{{{uuid_lib.uuid4()}}}"


def build_calls_auth_url(
    state_uuid: str | None = None,
    redirect_uri: str | None = None,
) -> tuple[str, str]:
    """
    URL VK Звонков (id.vk.com/auth?app_id=7793118&response_type=silent_token).
    redirect_uri по умолчанию vkcau:// — открывает приложение на ПК.
    Для админки используйте HTTPS callback или oauth.vk.com/blank.html.
    """
    uid = format_calls_uuid(state_uuid)
    params = {
        "app_id": str(VK_CALLS_APP_ID),
        "response_type": "silent_token",
        "uuid": uid,
        "v": VK_CALLS_AUTH_VERSION,
        "redirect_uri": redirect_uri or VK_CALLS_REDIRECT_URI,
    }
    url = f"https://id.vk.com/auth?{urlencode(params)}"
    return url, uid


def build_calls_admin_auth_urls(state: str, site_base: str = "") -> dict[str, str]:
    """
    VK app 7793118: redirect oauth.vk.com/blank.html → payload JSON с token+uuid.
    Kate Mobile OAuth в браузере заблокирован VK («direct auth»).
    """
    auth_calls_blank, _ = build_calls_auth_url(state, redirect_uri="https://oauth.vk.com/blank.html")
    auth_calls_blank_ru, _ = build_calls_auth_url(state, redirect_uri="https://oauth.vk.ru/blank.html")
    return {
        "auth_url": auth_calls_blank,
        "auth_url_calls": auth_calls_blank,
        "auth_url_calls_ru": auth_calls_blank_ru,
    }


def _parse_calls_payload_json(raw_payload: str) -> tuple[str | None, str | None]:
    """blank.html?payload={"type":"silent_token","token":"…","uuid":"{…}"}"""
    if not raw_payload:
        return None, None
    text = raw_payload.strip()
    if not text.startswith("{"):
        text = unquote(text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(obj, dict):
        return None, None
    token = obj.get("token") or obj.get("silent_token")
    uid = obj.get("uuid")
    if token and isinstance(token, str):
        token = token.strip()
    else:
        token = None
    return token, uid


def is_calls_login_start_url(text: str) -> bool:
    """Ссылка id.vk.com/auth?… без токена — это начало входа, не результат."""
    raw = (text or "").strip().lower()
    if not raw:
        return False
    if "silent_token=" in raw or "silent_token%3d" in raw:
        return False
    if "payload=" in raw and "silent_token" in raw:
        return False
    return "id.vk.com/auth" in raw and "app_id=7793118" in raw


def parse_silent_token_from_paste(text: str) -> tuple[str | None, str | None]:
    """Из blank.html?payload=…, vkcau://…#silent_token=… или произвольной строки."""
    raw = (text or "").strip()
    if not raw:
        return None, None

    parts: list[str] = []
    if raw.startswith("http") or "://" in raw:
        parsed = urlparse(raw)
        if parsed.query:
            parts.append(parsed.query)
        if parsed.fragment:
            parts.append(parsed.fragment.lstrip("#?"))
    else:
        if "#" in raw:
            parts.append(raw.split("#", 1)[-1])
        parts.append(raw.lstrip("?"))

    token: str | None = None
    uid: str | None = None
    for part in parts:
        params = dict(parse_qsl(part, keep_blank_values=True))
        payload_token, payload_uid = _parse_calls_payload_json(params.get("payload") or "")
        token = token or payload_token
        uid = uid or payload_uid
        token = token or params.get("silent_token") or params.get("token")
        uid = uid or params.get("uuid")

    if not token and "payload=" in raw:
        try:
            idx = raw.lower().index("payload=")
            chunk = raw[idx + len("payload="):]
            if "&" in chunk:
                chunk = chunk.split("&", 1)[0]
            payload_token, payload_uid = _parse_calls_payload_json(unquote(chunk))
            token = token or payload_token
            uid = uid or payload_uid
        except ValueError:
            pass

    if not token and "silent_token=" in raw:
        for chunk in raw.replace("&", " ").split():
            if chunk.startswith("silent_token="):
                token = chunk.split("=", 1)[1]
            if chunk.startswith("uuid="):
                uid = chunk.split("=", 1)[1]

    if token:
        token = token.strip()
    if uid:
        uid = format_calls_uuid(uid)
    return token, uid


async def _read_json(resp: aiohttp.ClientResponse) -> dict:
    text = await resp.text()
    if not text.strip():
        return {"error": "empty_response", "error_description": f"HTTP {resp.status}"}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "invalid_json", "error_description": text[:200]}


async def get_calls_anonym_token(device_id: str | None = None) -> tuple[str | None, str]:
    """Анонимный токен для обмена silent_token (app 7793118, secret не обязателен)."""
    device_id = (device_id or secrets.token_hex(16)).strip()
    headers = {"User-Agent": VK_USER_AGENT}
    secret = (settings.VK_CALLS_CLIENT_SECRET or "").strip()

    params: dict[str, str] = {
        "client_id": str(VK_CALLS_APP_ID),
        "device_id": device_id,
    }
    if secret:
        params["client_secret"] = secret

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get("https://oauth.vk.com/get_anonym_token", params=params) as resp:
                data = await _read_json(resp)
            token = data.get("token")
            if not token and isinstance(data.get("data"), dict):
                token = data["data"].get("access_token")
            if not token:
                token = data.get("access_token")
            if token:
                return str(token), "OK"
            err = data.get("error_description") or data.get("error") or str(data)[:120]
            logger.warning("get_anonym_token 7793118: %s", err)
    except Exception as e:
        logger.warning("get_anonym_token GET failed: %s", e)

    # login.vk.ru POST fallback
    try:
        payload = f"client_id={VK_CALLS_APP_ID}&version=1&app_id={VK_CALLS_APP_ID}"
        if secret:
            payload += f"&client_secret={secret}"
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(
                "https://login.vk.ru/?act=get_anonym_token",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                data = await _read_json(resp)
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            token = (inner or {}).get("access_token") or (inner or {}).get("token")
            if token:
                return str(token), "OK"
    except Exception as e:
        logger.warning("login.vk.ru get_anonym_token failed: %s", e)

    return None, "Не удалось получить anonym token для VK Звонков (app 7793118)"


async def exchange_silent_token(
    silent_token: str,
    token_uuid: str,
    device_id: str | None = None,
) -> tuple[str | None, int | None, str]:
    """
    silent_token + uuid → user access_token (vk1.a…), поддерживает calls.start.
    """
    silent_token = (silent_token or "").strip()
    token_uuid = format_calls_uuid(token_uuid)
    if not silent_token:
        return None, None, "Нет silent_token в вставке"

    anonym, err = await get_calls_anonym_token(device_id)
    if not anonym:
        return None, None, err

    try:
        payload = {
            "v": VK_API_VERSION,
            "access_token": anonym,
            "token": silent_token,
            "uuid": token_uuid,
        }
        async with aiohttp.ClientSession(
            headers={"User-Agent": VK_USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as session:
            async with session.post(
                "https://api.vk.com/method/auth.exchangeSilentAuthToken",
                data=payload,
            ) as resp:
                data = await _read_json(resp)
        if "error" in data:
            err_obj = data["error"]
            code = err_obj.get("error_code", 0)
            msg = err_obj.get("error_msg", "exchangeSilentAuthToken error")
            if code in (104, 106):
                msg = f"{msg}. Получите новый silent_token (срок жизни ~5 мин)."
            return None, None, msg

        resp = data.get("response") or {}
        access = resp.get("access_token")
        if not access:
            return None, None, "VK не вернул access_token после обмена"

        if resp.get("is_partial"):
            return None, None, "Токен partial — для агента нужен полный доступ к звонкам"
        if resp.get("additional_signup_required"):
            return None, None, "VK требует дополнительную регистрацию аккаунта"

        uid = resp.get("user_id")
        try:
            uid_int = int(uid) if uid is not None else None
        except (TypeError, ValueError):
            uid_int = None
        return access, uid_int, "OK"
    except Exception as e:
        logger.exception("exchange_silent_token failed")
        return None, None, str(e)
