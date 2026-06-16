"""VK ID linking — guest bootstrap before login + account attach after login."""
import json
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.database import get_db
from app.models import User, VkLinkSession
from app.core.deps import get_verified_user
from app.schemas.auth import (
    VkLinkStartResponse,
    VkLinkStatusResponse,
    VkGuestLinkStartResponse,
    VkGuestStatusResponse,
    VkGuestCompleteRequest,
    VkAttachRequest,
)
from app.services.vk_id_service import generate_pkce, build_authorize_url, exchange_code
from app.services.vk_config_publisher import publish_config_for_user
from app.services.vk_bootstrap import publish_bootstrap_to_vk_user
from app.services.vk_config_reader import fetch_config_from_vk_messages, fetch_bootstrap_hash_from_vk_messages
from app.services.vk_client_auth import (
    build_client_oauth_url,
    looks_like_vk_call_hash,
    verify_token_matches_user,
)
from app.services.vpn_service import get_active_vk_hashes
from app.config import settings
from app.schemas.vpn import VpnConfigResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/vk", tags=["vk-auth"])

LINK_TTL_MINUTES = 15


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Silent VPN</title>
<style>body{{font-family:sans-serif;text-align:center;padding:60px;background:#000;color:#fff}}
h2{{font-weight:400}}p{{color:#aaa;max-width:320px;margin:12px auto;line-height:1.5}}</style></head>
<body><h2>Ошибка</h2><p>{message}</p></body></html>""",
        status_code=status,
    )


def _success_page(vk_user_id: int, boot: str) -> HTMLResponse:
    deep_link = f"silentvpn://vk-linked?boot={boot}&vk={vk_user_id}" if boot else f"silentvpn://vk-linked?vk={vk_user_id}"
    link_js = json.dumps(deep_link)
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Silent VPN</title>
<style>body{{font-family:sans-serif;text-align:center;padding:60px;background:#000;color:#fff}}
h2{{font-weight:400}}p{{color:#aaa;max-width:340px;margin:12px auto;line-height:1.5}}
a{{color:#4680C2;text-decoration:none;font-size:16px;display:inline-block;margin-top:20px;padding:12px 24px;border:1px solid #4680C2;border-radius:8px}}</style></head>
<body><h2>VK подключён</h2>
<p>Первый хеш отправлен в сообщения VK автоматически.</p>
<a href="{deep_link}" id="openApp">Вернуться в Silent VPN</a>
<p id="hint" style="margin-top:24px;font-size:13px">Открываем приложение…</p>
<script>
(function(){{
  var link = {link_js};
  try {{ window.location.href = link; }} catch (e) {{}}
  setTimeout(function(){{
    var el = document.getElementById('hint');
    if (el) el.textContent = 'Вернитесь в окно Silent VPN на компьютере — данные уже сохранены.';
  }}, 1500);
}})();
</script>
</body></html>"""
    )


async def _start_session(db: AsyncSession, user_id=None, purpose: str = "guest") -> tuple[str, str, str]:
    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=LINK_TTL_MINUTES)
    if user_id:
        await db.execute(delete(VkLinkSession).where(VkLinkSession.user_id == user_id))
    elif purpose == "guest":
        await db.execute(
            delete(VkLinkSession).where(
                VkLinkSession.user_id.is_(None),
                VkLinkSession.purpose == "guest",
                VkLinkSession.expires_at < datetime.utcnow(),
            )
        )
    db.add(VkLinkSession(
        state=state,
        user_id=user_id,
        code_verifier=code_verifier,
        expires_at=expires_at,
        purpose=purpose,
    ))
    await db.commit()
    return state, code_verifier, build_authorize_url(state, code_challenge)


def _admin_agent_success_page(vk_user_id: int) -> HTMLResponse:
    return HTMLResponse(
        """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Silent Admin</title>
<style>body{font-family:sans-serif;text-align:center;padding:60px;background:#0a0a0a;color:#fff}
h2{font-weight:500;color:#4ade80}p{color:#888}</style></head>
<body><h2>VK подключён</h2>
<p>Аккаунт ID %d привязан к AI-агенту.</p>
<p>Закройте окно и нажмите «Подключить агента» в панели админа.</p>
<script>setTimeout(function(){window.close()},3000)</script>
</body></html>""" % vk_user_id
    )


async def _start_guest_android_session(db: AsyncSession) -> tuple[str, str]:
    """Guest bootstrap: Android OAuth token on device → calls.create locally."""
    state = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=LINK_TTL_MINUTES)
    await db.execute(
        delete(VkLinkSession).where(
            VkLinkSession.user_id.is_(None),
            VkLinkSession.purpose == "guest",
            VkLinkSession.expires_at < datetime.utcnow(),
        )
    )
    db.add(VkLinkSession(
        state=state,
        user_id=None,
        code_verifier="implicit",
        expires_at=expires_at,
        purpose="guest",
    ))
    await db.commit()
    return state, build_client_oauth_url(state)


async def complete_calls_silent_for_agent(
    db: AsyncSession,
    state: str,
    silent_token: str,
    token_uuid: str | None = None,
) -> tuple[bool, str, int | None]:
    """Обмен silent_token → vk1.a и сохранение для AI-агента."""
    from app.services.vk_agent_auth import save_agent_token_direct
    from app.services.vk_calls_auth import exchange_silent_token

    result = await db.execute(
        select(VkLinkSession).where(
            VkLinkSession.state == state,
            VkLinkSession.purpose == "agent",
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return False, "Сессия не найдена — обновите страницу /vk", None
    if session.expires_at < datetime.utcnow():
        return False, "Сессия истекла — нажмите «Войти» заново", None

    uuid_val = (token_uuid or session.code_verifier or "").strip()
    access, uid, err = await exchange_silent_token(silent_token, uuid_val)
    if not access:
        return False, err or "Не удалось обменять silent_token", None

    ok, msg, vk_uid = await save_agent_token_direct(db, access, None)
    if not ok:
        return False, msg, vk_uid

    session.vk_user_id = vk_uid or uid
    session.completed = True
    await db.commit()
    return True, msg, session.vk_user_id


@router.get("/calls-callback", response_class=HTMLResponse)
async def vk_calls_silent_callback(state: str = Query(default="")):
    """
    После входа VK Звонки редиректит сюда (не vkcau://).
    silent_token в #fragment — читаем в JS и POST на /calls-silent-finish.
    """
    state_js = json.dumps(state or "")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"><title>Silent — VK Звонки</title>
<style>
  body{{font-family:system-ui,sans-serif;text-align:center;padding:48px 20px;background:#0a0a0a;color:#fff}}
  h2{{font-weight:500;font-size:18px}} p{{color:#888;max-width:400px;margin:12px auto;line-height:1.55;font-size:14px}}
  .ok{{color:#4ade80}} .err{{color:#f87171}}
</style></head>
<body>
  <h2 id="title">Подключаем VK…</h2>
  <p id="msg">Обмениваем silent_token на сервере</p>
<script>
(function(){{
  var state = {state_js};
  function show(ok, title, text) {{
    document.getElementById('title').textContent = title;
    document.getElementById('title').className = ok ? 'ok' : 'err';
    document.getElementById('msg').textContent = text;
  }}
  if (!state) {{
    show(false, 'Ошибка', 'Нет state в URL. Закройте окно и нажмите «Войти в браузере» в админке.');
    return;
  }}
  var hash = (location.hash || '').replace(/^#/, '');
  var q = (location.search || '').replace(/^\\?/, '');
  var params = new URLSearchParams(hash || q);
  var silent = params.get('silent_token') || params.get('token');
  var uuid = params.get('uuid');
  var payloadRaw = params.get('payload');
  if (!silent && payloadRaw) {{
    try {{
      var pl = JSON.parse(decodeURIComponent(payloadRaw));
      if (pl && pl.token) {{
        silent = pl.token;
        uuid = uuid || pl.uuid;
      }}
    }} catch(e) {{}}
  }}
  if (!silent) {{
    show(false, 'Нет silent_token',
      'VK не вернул токен. Скопируйте URL oauth.vk.com/blank.html?payload=… и вставьте в админке.');
    return;
  }}
  fetch('/api/auth/vk/calls-silent-finish', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ state: state, silent_token: silent, uuid: uuid }})
  }}).then(function(r) {{ return r.json().then(function(d) {{ return {{ ok: r.ok, d: d }}; }}); }})
  .then(function(x) {{
    if (!x.ok) {{
      show(false, 'Ошибка', x.d.detail || 'Не удалось сохранить токен');
      return;
    }}
    show(true, 'VK подключён', 'Токен сохранён (ID ' + (x.d.vk_user_id || '—') + '). Закройте окно и нажмите «Подключить агента».');
    try {{ if (window.opener) window.opener.postMessage({{ type: 'vk-calls-auth-ok' }}, '*'); }} catch(e) {{}}
    setTimeout(function() {{ try {{ window.close(); }} catch(e) {{}} }}, 2500);
  }}).catch(function() {{
    show(false, 'Ошибка сети', 'Не удалось связаться с сервером Silent VPN');
  }});
}})();
</script>
</body></html>""")


class CallsSilentFinishRequest(BaseModel):
    state: str
    silent_token: str
    uuid: str | None = None


@router.post("/calls-silent-finish")
async def vk_calls_silent_finish(req: CallsSilentFinishRequest, db: AsyncSession = Depends(get_db)):
    ok, message, uid = await complete_calls_silent_for_agent(
        db, req.state.strip(), req.silent_token.strip(), req.uuid,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message, "vk_user_id": uid}


@router.post("/guest/link/start", response_model=VkGuestLinkStartResponse)
async def vk_guest_link_start(db: AsyncSession = Depends(get_db)):
    """Android VK OAuth на устройстве → клиент сам делает calls.create."""
    state, auth_url = await _start_guest_android_session(db)
    return VkGuestLinkStartResponse(auth_url=auth_url, state=state)


@router.post("/guest/complete")
async def vk_guest_complete(req: VkGuestCompleteRequest, db: AsyncSession = Depends(get_db)):
    """Клиент сообщает hash + token после calls.create (когда есть доступ к API)."""
    boot = req.bootstrap_hash.strip()
    if not looks_like_vk_call_hash(boot):
        raise HTTPException(status_code=400, detail="Некорректный хеш звонка VK")

    result = await db.execute(select(VkLinkSession).where(VkLinkSession.state == req.state))
    session = result.scalar_one_or_none()
    if not session or session.purpose != "guest":
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Сессия истекла")

    if not await verify_token_matches_user(req.access_token, req.vk_user_id):
        raise HTTPException(status_code=401, detail="VK token не совпадает с user_id")

    session.vk_user_id = req.vk_user_id
    session.bootstrap_hash = boot
    session.completed = True
    await db.commit()
    return {"ok": True, "bootstrap_hash": boot, "vk_user_id": req.vk_user_id}


@router.get("/guest/status", response_model=VkGuestStatusResponse)
async def vk_guest_status(state: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VkLinkSession).where(VkLinkSession.state == state))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    return VkGuestStatusResponse(
        completed=session.completed,
        vk_user_id=session.vk_user_id,
        bootstrap_hash=session.bootstrap_hash,
    )


@router.post("/link/start", response_model=VkLinkStartResponse)
async def vk_link_start(user: User = Depends(get_verified_user), db: AsyncSession = Depends(get_db)):
    if not settings.VK_ID_APP_ID:
        raise HTTPException(status_code=503, detail="VK ID не настроен на сервере")
    _, _, auth_url = await _start_session(db, user_id=user.id)
    return VkLinkStartResponse(auth_url=auth_url)


@router.post("/link/attach")
async def vk_link_attach(
    req: VkAttachRequest,
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    """Attach VK from guest flow after Silent login."""
    existing = await db.execute(
        select(User).where(User.vk_user_id == req.vk_user_id, User.id != user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Этот VK уже привязан к другому аккаунту")

    user.vk_user_id = req.vk_user_id
    user.vk_linked_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)

    try:
        await publish_config_for_user(db, user)
    except Exception as e:
        logger.warning("Config publish after attach failed: %s", e)

    hashes = await get_active_vk_hashes(db)
    return {
        "linked": True,
        "vk_user_id": user.vk_user_id,
        "bootstrap_hash": hashes[0] if hashes else None,
        "hashes": hashes,
    }


@router.get("/callback")
async def vk_oauth_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    device_id: str = Query(default=""),
    error: str = Query(default=""),
    error_description: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    if error:
        logger.warning("VK OAuth error: %s — %s", error, error_description)
        return _error_page(error_description or error)

    result = await db.execute(select(VkLinkSession).where(VkLinkSession.state == state))
    session = result.scalar_one_or_none()
    if session and getattr(session, "purpose", None) == "agent":
        return _error_page(
            "Для AI-агента нужен вход через VK Звонки (app 7793118), не VK ID. "
            "Админка → VK → «Открыть вход VK Звонки» → после входа вставьте URL "
            "vkcau://vk.com/auth#silent_token=…&uuid={…} в поле ниже.",
            status=400,
        )

    if not code or not state:
        return _error_page("Недействительный ответ VK. Повторите привязку.")

    if not session:
        return _error_page("Сессия привязки не найдена или истекла.")

    if session.expires_at < datetime.utcnow():
        await db.execute(delete(VkLinkSession).where(VkLinkSession.state == state))
        await db.commit()
        return _error_page("Время привязки истекло.")

    token_data = await exchange_code(code, session.code_verifier, device_id or "web", state)
    if not token_data:
        return _error_page("Не удалось получить токен VK ID.")

    vk_user_id = int(token_data.get("user_id", 0))
    if not vk_user_id:
        return _error_page("VK не вернул ID пользователя.")

    if getattr(session, "purpose", None) == "agent":
        from app.services.vk_agent_auth import complete_agent_auth

        access_token = token_data.get("access_token", "")
        expires_in = token_data.get("expires_in")
        ok, message, uid = await complete_agent_auth(db, state, access_token, expires_in)
        if not ok:
            hint = ""
            if "логин" in (message or "").lower() or "profile type" in (message or "").lower():
                hint = (
                    "<p style='margin-top:16px;color:#888'>Откройте админку → VK / Тоннели → "
                    "«Войти по логину и паролю». OAuth VK ID для агента не подходит.</p>"
                )
            return HTMLResponse(
                f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Silent — VK Agent</title>
<style>body{{font-family:sans-serif;text-align:center;padding:48px 24px;background:#000;color:#fff}}
h2{{font-weight:400;color:#f87171}}p{{color:#ccc;max-width:360px;margin:12px auto;line-height:1.55;font-size:15px}}</style></head>
<body><h2>Не удалось подключить агента</h2><p>{message or "Ошибка"}</p>{hint}</body></html>""",
                status_code=400,
            )
        return HTMLResponse(
            f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Silent — VK Agent</title>
<style>body{{font-family:sans-serif;text-align:center;padding:60px;background:#000;color:#fff}}
h2{{font-weight:400;color:#4ade80}}p{{color:#aaa;max-width:340px;margin:12px auto;line-height:1.5}}</style></head>
<body><h2>VK агент подключён</h2>
<p>ID {uid}. Закройте окно и в админке нажмите «Подключить агента».</p>
<script>setTimeout(function(){{try{{window.close()}}catch(e){{}}}},2500)</script>
</body></html>"""
        )

    _, boot = await publish_bootstrap_to_vk_user(db, vk_user_id)
    if not boot:
        hashes = await get_active_vk_hashes(db)
        boot = hashes[0] if hashes else ""

    session.vk_user_id = vk_user_id
    session.bootstrap_hash = boot or None
    session.completed = True

    if session.user_id is None:
        await db.commit()
        return _success_page(vk_user_id, boot or "")

    result = await db.execute(select(User).where(User.id == session.user_id))
    user = result.scalar_one_or_none()
    if not user:
        return _error_page("Пользователь не найден.", 404)

    existing = await db.execute(
        select(User).where(User.vk_user_id == vk_user_id, User.id != user.id)
    )
    if existing.scalar_one_or_none():
        return _error_page("Этот VK уже привязан к другому аккаунту Silent.", 409)

    user.vk_user_id = vk_user_id
    user.vk_linked_at = datetime.utcnow()
    await db.execute(delete(VkLinkSession).where(VkLinkSession.state == state))
    await db.commit()
    await db.refresh(user)

    try:
        await publish_config_for_user(db, user)
    except Exception as e:
        logger.warning("Initial VK config publish failed: %s", e)

    return _success_page(vk_user_id, boot or "")


@router.get("/config-sync", response_model=VpnConfigResponse)
async def vk_config_sync(
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.vk_user_id:
        raise HTTPException(status_code=400, detail="Сначала привяжите VK ID")
    if not settings.VK_COMMUNITY_TOKEN:
        raise HTTPException(status_code=503, detail="VK community token не настроен")

    config = await fetch_config_from_vk_messages(user.vk_user_id)
    if not config:
        try:
            await publish_config_for_user(db, user)
        except Exception as e:
            logger.warning("VK republish on sync failed: %s", e)
        config = await fetch_config_from_vk_messages(user.vk_user_id)

    if not config:
        raise HTTPException(status_code=404, detail="Конфиг в сообщениях VK не найден.")
    return config


@router.get("/bootstrap-hash")
async def vk_bootstrap_hash(
    user: User = Depends(get_verified_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.vk_user_id:
        raise HTTPException(status_code=400, detail="Сначала привяжите VK ID")

    hashes = await get_active_vk_hashes(db)
    boot = hashes[0] if hashes else None
    if not boot:
        boot = await fetch_bootstrap_hash_from_vk_messages(user.vk_user_id)
    if not boot:
        raise HTTPException(status_code=404, detail="Хеш в VK не найден.")
    return {"bootstrap_hash": boot, "hashes": hashes}


@router.get("/status", response_model=VkLinkStatusResponse)
async def vk_link_status(user: User = Depends(get_verified_user), db: AsyncSession = Depends(get_db)):
    boot: str | None = None
    if user.vk_user_id:
        hashes = await get_active_vk_hashes(db)
        boot = hashes[0] if hashes else None
        if not boot:
            boot = await fetch_bootstrap_hash_from_vk_messages(user.vk_user_id)
    return VkLinkStatusResponse(
        linked=user.vk_user_id is not None,
        vk_user_id=user.vk_user_id,
        linked_at=user.vk_linked_at,
        bootstrap_hash=boot,
    )
