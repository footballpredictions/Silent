"""VK Звонки (calls.vk.com) — silent_token → access_token для calls.start."""
from __future__ import annotations

import json
import logging
import secrets
import uuid as uuid_lib
from urllib.parse import parse_qsl, urlencode, urlparse

import aiohttp

from app.config import settings
from app.services.vk_agent_auth import VK_API_VERSION, VK_USER_AGENT, vk_api_call

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


def build_calls_auth_url(state_uuid: str | None = None) -> tuple[str, str]:
    """
    URL как на calls.vk.com / id.vk.com для VK Звонков.
    Возвращает (auth_url, uuid_with_braces).
    """
    uid = format_calls_uuid(state_uuid)
    params = {
        "app_id": str(VK_CALLS_APP_ID),
        "response_type": "silent_token",
        "uuid": uid,
        "v": VK_CALLS_AUTH_VERSION,
        "redirect_uri": VK_CALLS_REDIRECT_URI,
    }
    url = f"https://id.vk.com/auth?{urlencode(params)}"
    return url, uid


def parse_silent_token_from_paste(text: str) -> tuple[str | None, str | None]:
    """Из vkcau://…#silent_token=…&uuid=… или произвольной строки."""
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
        token = token or params.get("silent_token") or params.get("token")
        uid = uid or params.get("uuid")

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
    """Анонимный токен для обмена silent_token (как VK Calls desktop)."""
    secret = (settings.VK_CALLS_CLIENT_SECRET or "").strip()
    if not secret:
        return None, "VK_CALLS_CLIENT_SECRET не задан в .env на сервере"

    device_id = (device_id or secrets.token_hex(16)).strip()
    headers = {"User-Agent": VK_USER_AGENT}

    # 1) oauth.vk.com/get_anonym_token (как в логах VK Calls)
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(
                "https://oauth.vk.com/get_anonym_token",
                params={
                    "client_id": str(VK_CALLS_APP_ID),
                    "client_secret": secret,
                    "device_id": device_id,
                },
            ) as resp:
                data = await _read_json(resp)
            token = (data.get("data") or {}).get("access_token") or data.get("access_token")
            if token:
                return token, "OK"
            if data.get("token"):
                return data["token"], "OK"
    except Exception as e:
        logger.warning("get_anonym_token GET failed: %s", e)

    # 2) login.vk.ru POST (как wdtt-go)
    try:
        payload = (
            f"client_id={VK_CALLS_APP_ID}&client_secret={secret}"
            f"&version=1&app_id={VK_CALLS_APP_ID}"
        )
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(
                "https://login.vk.ru/?act=get_anonym_token",
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                data = await _read_json(resp)
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            token = (inner or {}).get("access_token")
            if token:
                return token, "OK"
    except Exception as e:
        logger.warning("login.vk.ru get_anonym_token failed: %s", e)

    # 3) API method auth.getAnonymToken
    try:
        data = await vk_api_call(
            "auth.getAnonymToken",
            "",
            {"client_id": str(VK_CALLS_APP_ID), "client_secret": secret},
        )
        if "error" in data:
            err = data["error"]
            return None, err.get("error_msg", str(err))
        resp = data.get("response") or {}
        token = resp.get("token") or resp.get("access_token")
        if token:
            return token, "OK"
    except Exception as e:
        logger.warning("auth.getAnonymToken failed: %s", e)

    return None, "Не удалось получить anonym token для VK Звонков"


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
        data = await vk_api_call(
            "auth.exchangeSilentAuthToken",
            anonym,
            {"token": silent_token, "uuid": token_uuid},
        )
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
