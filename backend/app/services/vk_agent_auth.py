"""VK agent auth — Android client OAuth (same as proxy-turn-vk-android)."""
from __future__ import annotations

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

# Official / widely used Android client IDs with secrets (for password grant)
VK_ANDROID_CLIENTS = [
    {"id": 6287487, "secret": "VeWdmVclDCtn6ihuP1nt"},
    {"id": 2274003, "secret": "hHbZxrka2uZ6jB1inYsH"},
    {"id": 2685278, "secret": "lxhD8OD7dMsqtXIm5IUY"},
    {"id": 8202606, "secret": ""},
]

VK_ANDROID_CLIENT_ID = 6287487
VK_ANDROID_CLIENT_SECRET = "VeWdmVclDCtn6ihuP1nt"
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

    if fragment and "access_token=" in fragment:
        params = dict(parse_qsl(fragment.lstrip("#?"), keep_blank_values=True))
        token = params.get("access_token")
        state = params.get("state")
        exp = params.get("expires_in")
        return None, token, state, int(exp) if exp and str(exp).isdigit() else None

    if raw.startswith("vk1."):
        return None, raw, None, None

    return None, None, None, None


def build_agent_auth_url(state: str, _base_url: str = "") -> str:
    """Android OAuth code flow — token выдаётся серверу (IP VPS)."""
    from urllib.parse import urlencode
    redirect_uri = VK_ANDROID_REDIRECT_URI
    params = {
        "client_id": str(VK_ANDROID_CLIENT_ID),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "offline",
        "state": state,
        "display": "page",
        "v": VK_API_VERSION,
    }
    return f"https://oauth.vk.com/authorize?{urlencode(params)}"


async def exchange_android_code(code: str, redirect_uri: str) -> tuple[dict | None, str | None]:
    """Один обмен code→token. Повторы только при обрыве сети (не при ошибке VK)."""
    last_err: str | None = None
    for attempt in range(2):
        try:
            async with aiohttp.ClientSession(
                headers={"User-Agent": VK_USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=45),
            ) as session:
                async with session.post(
                    "https://oauth.vk.com/token",
                    data={
                        "grant_type": "authorization_code",
                        "client_id": str(VK_ANDROID_CLIENT_ID),
                        "client_secret": VK_ANDROID_CLIENT_SECRET,
                        "redirect_uri": redirect_uri,
                        "code": code,
                    },
                ) as resp:
                    data = await resp.json(content_type=None)
            if "access_token" in data:
                return data, None
            last_err = data.get("error_description") or data.get("error") or str(data)
            logger.warning("Android code exchange failed: %s", data)
            # Ошибка VK (неверный/использованный code, flood) — не ретраим
            return None, last_err
        except Exception as e:
            last_err = str(e)
            logger.warning("Android code exchange network attempt %s: %s", attempt + 1, e)
    return None, last_err or "Server disconnected"


async def paste_to_server_token(paste: str) -> tuple[str | None, int | None, str]:
    """
    code из URL → обмен на сервере (IP VPS).
    access_token из браузера → отклонить (другой IP).
    """
    code, token, _, exp = parse_vk_oauth_paste(paste)
    if code:
        data, err = await exchange_android_code(code, VK_ANDROID_REDIRECT_URI)
        if not data:
            msg = err or "Не удалось обменять code на token"
            if err and "too many" in err.lower():
                msg = (
                    "VK временно заблокировал запросы (лимит 15 сек). "
                    "Подождите 1–2 минуты, нажмите «Войти через VK» заново и вставьте свежий URL с code= "
                    "(старый code одноразовый)."
                )
            return None, None, msg
        return data["access_token"], data.get("expires_in"), ""
    if token:
        return None, None, (
            "Токен vk1.a с вашего компьютера не подходит — VK привязывает его к вашему IP. "
            "Вставьте URL с code= (blank.html?code=...), сервер получит token сам."
        )
    return None, None, (
        "Не найден code= в URL. После входа скопируйте адрес blank.html?code=..."
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
    """Password grant via Android client_id + secret (с IP сервера)."""
    last_err = "Не удалось авторизоваться"
    for client in VK_ANDROID_CLIENTS:
        if not client.get("secret"):
            continue
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession(
                    headers={"User-Agent": VK_USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as session:
                    payload = {
                        "grant_type": "password",
                        "client_id": str(client["id"]),
                        "client_secret": client["secret"],
                        "username": login,
                        "password": password,
                        "scope": "offline",
                        "v": VK_API_VERSION,
                    }
                    async with session.post("https://oauth.vk.com/token", data=payload) as resp:
                        data = await resp.json(content_type=None)
                if "access_token" in data:
                    logger.info("VK password auth OK with client_id=%s", client["id"])
                    return data["access_token"], f"Авторизация через client_id {client['id']}"
                last_err = data.get("error_description") or data.get("error", last_err)
                logger.warning("VK auth client_id=%s: %s", client["id"], last_err)
                break
            except Exception as e:
                last_err = str(e) or "Server disconnected"
                logger.warning("VK auth client_id=%s attempt %s: %s", client["id"], attempt + 1, e)
    return None, last_err


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
