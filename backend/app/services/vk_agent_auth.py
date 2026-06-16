"""VK agent auth — Android client OAuth (same as proxy-turn-vk-android)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import VkCredentials
from app.core.security import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)

VK_API_VERSION = "5.199"
VK_USER_AGENT = (
    "VKAndroidApp/8.10-17765 (Android 14; SDK 34; arm64-v8a; Google Pixel 8; ru; 2560x1080)"
)

# Kate Mobile / Android standalone — рабочий client для password/code grant (6287487 secret отозван VK)
VK_ANDROID_CLIENTS = [
    {"id": 2274003, "secret": "hHbZxrka2uZ6jB1inYsH"},
    {"id": 2685278, "secret": "lxhD8OD7dMsqtXIm5IUY"},
    {"id": 6287487, "secret": "VeWdmVclDCtn6ihuP1nt"},
    {"id": 8202606, "secret": ""},
]

VK_ANDROID_CLIENT_ID = 2274003
VK_ANDROID_CLIENT_SECRET = "hHbZxrka2uZ6jB1inYsH"
# Единственный redirect для официального Android client_id (нельзя добавить свой домен)
VK_ANDROID_REDIRECT_URI = "https://oauth.vk.com/blank.html"


def agent_oauth_redirect_uri(_base_url: str = "") -> str:
    return VK_ANDROID_REDIRECT_URI


def parse_vk_oauth_paste(text: str) -> tuple[str | None, str | None, str | None, int | None]:
    """
    Returns: (code, access_token, state, expires_in)
    """
    from urllib.parse import parse_qsl, urlparse

    raw = (text or "").strip()
    if not raw:
        return None, None, None, None

    query_part = ""
    fragment = ""
    if raw.startswith("http"):
        parsed = urlparse(raw)
        query_part = parsed.query or ""
        fragment = parsed.fragment or ""
    else:
        query_part = raw.lstrip("?")
        fragment = raw.split("#", 1)[-1] if "#" in raw else ""

    if query_part and "code=" in query_part:
        params = dict(parse_qsl(query_part, keep_blank_values=True))
        code = params.get("code")
        state = params.get("state")
        if code:
            return code, None, state, None

    if fragment:
        params = dict(parse_qsl(fragment.lstrip("#?"), keep_blank_values=True))
        code = params.get("code")
        if code:
            return code, None, params.get("state"), None
        token = params.get("access_token")
        if token:
            exp = params.get("expires_in")
            return None, token, params.get("state"), int(exp) if exp and str(exp).isdigit() else None

    if raw.startswith("vk1.") or raw.startswith("vk2."):
        return None, raw, None, None

    return None, None, None, None


def parse_device_id_from_paste(text: str) -> str | None:
    from urllib.parse import parse_qsl, urlparse

    raw = (text or "").strip()
    if not raw:
        return None
    parts: list[str] = []
    if raw.startswith("http"):
        parsed = urlparse(raw)
        if parsed.query:
            parts.append(parsed.query)
        if parsed.fragment:
            parts.append(parsed.fragment.lstrip("#?"))
    else:
        if "#" in raw:
            parts.append(raw.split("#", 1)[-1])
        parts.append(raw.lstrip("?"))
    for part in parts:
        params = dict(parse_qsl(part, keep_blank_values=True))
        did = (params.get("device_id") or "").strip()
        if did:
            return did
    return None


def redirect_uri_from_oauth_paste(paste: str) -> str:
    """redirect_uri для обмена code — должен совпадать с blank.html из URL пользователя."""
    s = (paste or "").lower()
    if "oauth.vk.ru" in s:
        return "https://oauth.vk.ru/blank.html"
    return VK_ANDROID_REDIRECT_URI


def build_kate_oauth_url(state: str) -> str:
    """Kate Mobile code flow — blank.html, токен vk1.a с calls.start (без пароля)."""
    from urllib.parse import urlencode

    params = {
        "client_id": str(VK_ANDROID_CLIENT_ID),
        "redirect_uri": VK_ANDROID_REDIRECT_URI,
        "response_type": "code",
        "scope": "offline",
        "state": state,
        "display": "mobile",
        "revoke": "1",
    }
    return f"https://oauth.vk.ru/authorize?{urlencode(params)}"


def build_agent_auth_url(state: str, code_challenge: str = "", _base_url: str = "") -> str:
    """Только VK Звонки: id.vk.com/auth?app_id=7793118&response_type=silent_token."""
    from app.services.vk_calls_auth import build_calls_auth_url

    url, _ = build_calls_auth_url(state)
    return url


async def _read_vk_oauth_json(resp: aiohttp.ClientResponse) -> dict:
    text = await resp.text()
    if not text.strip():
        return {
            "error": "empty_response",
            "error_description": (
                f"Пустой ответ VK (HTTP {resp.status}). "
                "Подождите 2–3 минуты и получите новый code через OAuth."
            ),
        }
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "error": "invalid_response",
            "error_description": f"VK вернул не JSON (HTTP {resp.status}): {text[:120]}",
        }


async def exchange_android_code(code: str, redirect_uri: str) -> tuple[dict | None, str | None]:
    """Обмен code→token через oauth.vk.com. Один redirect, один запрос."""
    payload = {
        "grant_type": "authorization_code",
        "client_id": str(VK_ANDROID_CLIENT_ID),
        "client_secret": VK_ANDROID_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": VK_USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=45),
        ) as session:
            async with session.post("https://oauth.vk.com/token", data=payload) as resp:
                data = await _read_vk_oauth_json(resp)
            if "access_token" in data:
                return data, None
            err = data.get("error_description") or data.get("error") or str(data)
            logger.warning("Code exchange redirect=%s: %s", redirect_uri, data)
            return None, err
    except Exception as e:
        logger.warning("Android code exchange failed: %s", e)
        return None, str(e)


async def exchange_vkid_agent_code(
    db: AsyncSession,
    code: str,
    state: str,
    device_id: str | None = None,
) -> tuple[dict | None, str | None]:
    """Обмен code→token через VK ID (PKCE + device_id из сессии админки)."""
    from app.models import VkLinkSession
    from app.services.vk_id_service import exchange_code

    result = await db.execute(
        select(VkLinkSession).where(
            VkLinkSession.state == state,
            VkLinkSession.purpose == "agent",
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None, "Сессия OAuth не найдена — обновите страницу /vk и откройте ссылку заново"
    if session.expires_at < datetime.utcnow():
        return None, "Сессия OAuth истекла — обновите страницу /vk"

    token_data = await exchange_code(
        code,
        session.code_verifier,
        (device_id or "web").strip() or "web",
        state,
    )
    if not token_data or not token_data.get("access_token"):
        return None, "VK ID не выдал access_token — проверьте redirect URI в кабинете VK ID"
    return token_data, None


async def paste_to_server_token(
    paste: str,
    db: AsyncSession | None = None,
) -> tuple[str | None, int | None, str]:
    """
    silent_token (VK Звонки) → code (Kate/Android) → VK ID (PKCE).
    Обмен на сервере (IP VPS).
    """
    from app.services.vk_calls_auth import parse_silent_token_from_paste, exchange_silent_token

    silent, silent_uuid = parse_silent_token_from_paste(paste)
    if silent:
        access, uid, err = await exchange_silent_token(silent, silent_uuid or "")
        if access:
            return access, None, ""
        return None, None, err or "Не удалось обменять silent_token"

    code, token, state, _ = parse_vk_oauth_paste(paste)
    device_id = parse_device_id_from_paste(paste)

    if code and db and state:
        token_data, err = await exchange_vkid_agent_code(db, code, state, device_id)
        if token_data:
            exp = token_data.get("expires_in")
            return token_data["access_token"], int(exp) if exp else None, ""
        if err and "не найдена" not in err.lower() and "истекла" not in err.lower():
            return None, None, err

    if code:
        redirect_uri = redirect_uri_from_oauth_paste(paste)
        data, err = await exchange_android_code(code, redirect_uri)
        if not data:
            msg = err or "Не удалось обменять code на token"
            if err and "too many" in err.lower():
                msg = (
                    "VK: слишком много запросов. Подождите 5 минут, "
                    "откройте OAuth заново (code одноразовый)."
                )
            elif err and ("invalid_grant" in err.lower() or "invalid" in err.lower() or "expired" in err.lower()):
                msg = f"{err}. Нажмите «Открыть VK OAuth» ещё раз (не Kate/direct auth)."
            elif err and "direct auth" in err.lower():
                msg = "Этот OAuth недоступен в браузере. Используйте кнопку «Открыть VK OAuth» на странице /vk."
            return None, None, msg
        return data["access_token"], data.get("expires_in"), ""
    if token:
        return None, None, (
            "Токен vk1.a/vk2.a с вашего компьютера не подходит — VK привязывает его к вашему IP. "
            "Используйте VK Звонки: id.vk.com/auth?app_id=7793118 → вставьте vkcau://…#silent_token=…"
        )
    return None, None, (
        "Не найден silent_token. Откройте «VK Звонки» в админке, войдите и вставьте URL "
        "vkcau://vk.com/auth#silent_token=…&uuid={…} (как на calls.vk.com)."
    )


async def complete_agent_auth(
    db: AsyncSession,
    state: str,
    access_token: str,
    expires_in: int | None = None,
) -> tuple[bool, str, int | None]:
    """Validate session, save Android token, verify calls.create."""
    from app.models import VkLinkSession
    from datetime import datetime

    result = await db.execute(
        select(VkLinkSession).where(
            VkLinkSession.state == state,
            VkLinkSession.purpose == "agent",
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return False, "Сессия не найдена", None
    if session.expires_at < datetime.utcnow():
        return False, "Сессия истекла — повторите вход", None
    if session.completed:
        ok, _, uid = await validate_token(access_token)
        return ok, "Уже авторизован", uid

    await save_stored_token(db, access_token, expires_in)
    ok, msg, uid = await validate_token(access_token)
    if not ok:
        return False, msg, None
    calls_ok, calls_msg = await test_calls_permission(access_token)
    if not calls_ok:
        await set_calls_verified(db, False)
        low = (calls_msg or "").lower()
        if access_token.startswith("vk2.") or "profile type" in low or "unavailable with current profile" in low:
            return False, (
                "Токен VK ID не создаёт звонки (calls.start). "
                "Для агента нужен вход по логину и паролю VK в админке → раздел /vk."
            ), uid
        return False, f"Звонки недоступны: {calls_msg}", uid

    session.vk_user_id = uid
    session.completed = True
    await set_calls_verified(db, True)
    await db.commit()
    return True, "OK", uid


async def vk_api_call(method: str, token: str, params: dict | None = None) -> dict:
    """VK API via GET (как test_calls.py)."""
    q = {"access_token": token, "v": VK_API_VERSION}
    if params:
        q.update(params)
    async with aiohttp.ClientSession(
        headers={"User-Agent": VK_USER_AGENT},
        timeout=aiohttp.ClientTimeout(total=30),
    ) as session:
        async with session.get(f"https://api.vk.com/method/{method}", params=q) as resp:
            return await resp.json(content_type=None)


async def _api_get(method: str, token: str, extra: dict | None = None) -> dict:
    return await vk_api_call(method, token, extra)


async def validate_token(token: str) -> tuple[bool, str, int | None]:
    """Returns (ok, message, vk_user_id)."""
    if not token or len(token) < 20:
        return False, "Токен пустой или слишком короткий", None
    try:
        data = await _api_get("users.get", token)
        if "error" in data:
            err = data["error"]
            return False, err.get("error_msg", "VK API error"), None
        users = data.get("response", [])
        if not users:
            return False, "users.get вернул пустой ответ", None
        uid = users[0].get("id")
        return True, f"OK, user_id={uid}", uid
    except Exception as e:
        return False, str(e), None


async def test_calls_permission(token: str) -> tuple[bool, str]:
    """Check calls.start (Android token only)."""
    if (token or "").startswith("vk2."):
        return False, "VK ID token (vk2.a) не поддерживает calls.start"
    try:
        data = await vk_api_call("calls.start", token)
        if "error" in data:
            err = data["error"]
            return False, err.get("error_msg", "calls.start denied")
        join = data.get("response", {}).get("join_link", "")
        if join:
            return True, "OK"
        return False, "calls.start без join_link"
    except Exception as e:
        return False, str(e)


async def password_login(login: str, password: str) -> tuple[str | None, str]:
    """Password grant via Android client_id + secret (с IP сервера). Один запрос — без flood VK."""
    payload = {
        "grant_type": "password",
        "client_id": str(VK_ANDROID_CLIENT_ID),
        "client_secret": VK_ANDROID_CLIENT_SECRET,
        "username": login.strip(),
        "password": password,
        "scope": "offline",
        "2fa_supported": "1",
        "v": VK_API_VERSION,
    }
    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": VK_USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=45),
        ) as session:
            async with session.post("https://oauth.vk.com/token", data=payload) as resp:
                data = await _read_vk_oauth_json(resp)
        if "access_token" in data:
            return data["access_token"], "Авторизация OK"
        err = data.get("error_description") or data.get("error") or "Не удалось авторизоваться"
        low = err.lower()
        if "too many" in low or "flood" in low or "pogingen" in low or "paar uur" in low:
            return None, (
                "VK заблокировал вход по паролю на несколько часов (слишком много попыток). "
                "Подождите 3–6 часов и нажмите «Войти» ещё раз — только один раз."
            )
        if "need_validation" in low or "validation" in low:
            return None, "VK запросил SMS-код (2FA). Пока не поддерживается — отключите 2FA или используйте другой аккаунт."
        return None, err
    except Exception as e:
        return None, str(e) or "Server disconnected"


async def load_stored_token(db: AsyncSession) -> str | None:
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    if not creds or not creds.access_token:
        return None
    try:
        token = decrypt_value(creds.access_token)
        if creds.token_expires and creds.token_expires < datetime.utcnow():
            logger.warning("Stored VK token expired at %s", creds.token_expires)
            return None
        return token
    except Exception as e:
        logger.error("Failed to decrypt VK token: %s", e)
        return None


async def save_stored_token(db: AsyncSession, token: str, expires_in: int | None = None) -> None:
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    enc = encrypt_value(token)
    expires = None
    if expires_in:
        expires = datetime.utcnow() + timedelta(seconds=int(expires_in))
    if creds:
        creds.access_token = enc
        creds.token_expires = expires
        creds.is_configured = True
    else:
        db.add(VkCredentials(
            id=1,
            access_token=enc,
            token_expires=expires,
            is_configured=True,
        ))
    await db.commit()


async def save_agent_credentials(db: AsyncSession, login: str, password: str) -> None:
    """Сохранить логин/пароль для повторного password grant (когда VK снимет flood)."""
    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    enc_login = encrypt_value(login.strip())
    enc_pass = encrypt_value(password)
    if creds:
        creds.login_enc = enc_login
        creds.password_enc = enc_pass
    else:
        db.add(VkCredentials(
            id=1,
            login_enc=enc_login,
            password_enc=enc_pass,
            is_configured=False,
        ))
    await db.commit()


async def save_agent_token_direct(
    db: AsyncSession,
    access_token: str,
    expires_in: int | None = None,
) -> tuple[bool, str, int | None]:
    """Save Android token without OAuth session (admin paste vk1.a...)."""
    await save_stored_token(db, access_token, expires_in)
    ok, msg, uid = await validate_token(access_token)
    if not ok:
        return False, msg, None
    calls_ok, calls_msg = await test_calls_permission(access_token)
    if not calls_ok:
        await set_calls_verified(db, False)
        return False, f"Звонки недоступны: {calls_msg}", uid
    await set_calls_verified(db, True)
    await db.commit()
    return True, "OK", uid


def get_env_agent_token() -> str | None:
    from app.config import settings
    t = (settings.VK_AGENT_ACCESS_TOKEN or "").strip()
    return t if len(t) > 20 else None


async def resolve_agent_token(db: AsyncSession, *, verify_calls: bool = False) -> tuple[str | None, str]:
    """
    Токен для API. verify_calls=True — проверить calls.create (только при connect, не при status).
    """
    from app.config import settings

    env_tok = get_env_agent_token()
    if env_tok:
        ok, msg, _ = await validate_token(env_tok)
        if ok:
            if verify_calls:
                c_ok, c_msg = await test_calls_permission(env_tok)
                if c_ok:
                    await save_stored_token(db, env_tok)
                    await set_calls_verified(db, True)
                    return env_tok, "Токен из VK_AGENT_ACCESS_TOKEN (.env)"
                logger.warning("VK_AGENT_ACCESS_TOKEN: calls.create failed: %s", c_msg)
            else:
                return env_tok, "Токен из .env"
        else:
            logger.warning("VK_AGENT_ACCESS_TOKEN invalid (%s)", msg)

    stored = await load_stored_token(db)
    if stored:
        ok, msg, _ = await validate_token(stored)
        if ok:
            if verify_calls:
                c_ok, c_msg = await test_calls_permission(stored)
                if c_ok:
                    await set_calls_verified(db, True)
                    return stored, msg
                logger.warning("Stored token calls.create: %s", c_msg)
            else:
                return stored, msg

    if verify_calls and settings.VK_LOGIN and settings.VK_PASSWORD:
        token, msg = await password_login(settings.VK_LOGIN, settings.VK_PASSWORD)
        if token:
            c_ok, c_msg = await test_calls_permission(token)
            if c_ok:
                await save_stored_token(db, token)
                await set_calls_verified(db, True)
                return token, f"Авторизация из .env (VK_LOGIN): {msg}"
            return None, f"VK_LOGIN/PASSWORD: звонки недоступны: {c_msg}"
        return None, msg

    if verify_calls:
        result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
        creds = result.scalar_one_or_none()
        if creds and creds.login_enc and creds.password_enc:
            try:
                login = decrypt_value(creds.login_enc)
                password = decrypt_value(creds.password_enc)
                token, msg = await password_login(login, password)
                if token:
                    c_ok, c_msg = await test_calls_permission(token)
                    if c_ok:
                        await save_stored_token(db, token)
                        await set_calls_verified(db, True)
                        return token, msg
                    return None, f"Звонки недоступны: {c_msg}"
                return None, msg
            except Exception as e:
                return None, str(e)

    if stored := await load_stored_token(db):
        ok, msg, _ = await validate_token(stored)
        if ok:
            return stored, msg

    return None, "Войдите через VK (кнопка выше) и вставьте URL с code="


async def _setting(db: AsyncSession, key: str) -> str | None:
    from app.models import AppSetting
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = r.scalar_one_or_none()
    return s.value if s else None


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    from app.models import AppSetting
    r = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = r.scalar_one_or_none()
    if s:
        s.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    await db.commit()


async def set_calls_verified(db: AsyncSession, ok: bool) -> None:
    await _set_setting(db, "vk_agent_calls_ok", "true" if ok else "false")


async def get_calls_verified(db: AsyncSession) -> bool:
    return (await _setting(db, "vk_agent_calls_ok")) == "true"


async def is_agent_enabled(db: AsyncSession) -> bool:
    from app.models import AppSetting
    result = await db.execute(select(AppSetting).where(AppSetting.key == "vk_agent_enabled"))
    s = result.scalar_one_or_none()
    return s is not None and s.value == "true"


async def set_agent_enabled(db: AsyncSession, enabled: bool) -> None:
    from app.models import AppSetting
    key = "vk_agent_enabled"
    result = await db.execute(select(AppSetting).where(AppSetting.key == key))
    s = result.scalar_one_or_none()
    if s:
        s.value = "true" if enabled else "false"
    else:
        db.add(AppSetting(key=key, value="true" if enabled else "false"))
    await db.commit()


async def get_auth_status(db: AsyncSession) -> dict:
    """Статус без лишних запросов к VK (без calls.create / password grant)."""
    from app.config import settings

    result = await db.execute(select(VkCredentials).where(VkCredentials.id == 1))
    creds = result.scalar_one_or_none()
    has_token = bool(creds and creds.access_token)

    auth_ok = False
    auth_error: str | None = None
    vk_user_id: int | None = None
    calls_ok = await get_calls_verified(db)

    token, msg = await resolve_agent_token(db, verify_calls=False)
    if token:
        ok, detail, uid = await validate_token(token)
        auth_ok = ok
        vk_user_id = uid
        if not ok:
            auth_error = detail
        elif not calls_ok:
            auth_error = None  # токен есть, calls проверим при «Подключить агента»
    elif has_token:
        auth_error = "Токен в БД устарел — войдите через VK заново"
    else:
        auth_error = msg if msg else None

    agent_on = await is_agent_enabled(db)

    env_warn: str | None = None
    env_tok = get_env_agent_token()
    if env_tok and not auth_ok:
        env_warn = "VK_AGENT_ACCESS_TOKEN в .env не прошёл users.get — обновите или удалите"

    return {
        "bot_url": settings.VK_BOT_WRITE_URL or f"https://vk.com/write-{settings.VK_GROUP_ID}",
        "group_id": settings.VK_GROUP_ID,
        "vk_linked": auth_ok,
        "calls_ok": calls_ok,
        "auth_error": auth_error,
        "vk_user_id": vk_user_id,
        "agent_connected": agent_on and auth_ok and calls_ok,
        "agent_enabled": agent_on,
        "has_token": has_token,
        "env_token_set": env_tok is not None,
        "env_token_warn": env_warn,
    }
