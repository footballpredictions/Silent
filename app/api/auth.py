from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
import json
import logging

logger = logging.getLogger(__name__)

from app.database import get_db
from app.models import User
from app.schemas.auth import (
    RegisterRequest, LoginRequest, TokenResponse,
    RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest,
    AdminLoginRequest, AdminTokenResponse,
)
from app.core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    generate_token,
)
from app.services.email_service import send_verification_email, send_password_reset_email
from app.services.subscription_service import apply_post_verification_benefits
from app.services.theme_settings import load_theme
from app.services.vpn_service import ensure_device_session
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    req: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")

    token = generate_token()
    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        verification_token=token,
    )
    db.add(user)
    await db.commit()

    # Отправка письма в фоне — не блокирует ответ клиенту
    base_url = settings.FRONTEND_URL.rstrip("/")
    background_tasks.add_task(send_verification_email, req.email, token, base_url)
    logger.info(f"Register: {req.email}, verify link base: {base_url}")

    return {"message": "Регистрация успешна. Проверьте email для подтверждения."}


@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.verification_token == token))
    user = result.scalar_one_or_none()

    if not user:
        return HTMLResponse(_html_page(
            success=False,
            title="Ссылка недействительна",
            message="Токен подтверждения устарел или уже был использован.",
        ), status_code=400)

    user.is_verified = True
    user.verification_token = None
    await db.commit()
    await apply_post_verification_benefits(db, user)

    return HTMLResponse(_html_page(
        success=True,
        title="Email подтверждён!",
        message=f"Аккаунт <strong>{user.email}</strong> успешно активирован.<br>Теперь вы можете войти в приложение.",
    ))


def _html_page(success: bool, title: str, message: str) -> str:
    icon = "✓" if success else "✗"
    color = "#22c55e" if success else "#ef4444"
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Silent VPN — {title}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0a0a0a;font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:16px}}
  .card{{background:#111;border:1px solid #222;border-radius:16px;padding:48px 40px;max-width:480px;width:100%;text-align:center}}
  .icon{{width:72px;height:72px;background:{color}22;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 24px;font-size:32px;color:{color}}}
  .brand{{color:#fff;font-size:13px;font-weight:700;letter-spacing:3px;margin-bottom:32px;opacity:0.5}}
  h1{{color:#fff;font-size:22px;font-weight:700;margin-bottom:16px}}
  p{{color:#888;font-size:15px;line-height:1.7}}
  p strong{{color:#ccc}}
  .hint{{margin-top:24px;color:#555;font-size:13px}}
</style>
</head>
<body>
<div class="card">
  <div class="brand">SILENT VPN</div>
  <div class="icon">{icon}</div>
  <h1>{title}</h1>
  <p>{message}</p>
  <p class="hint">Можно закрыть эту страницу и вернуться в приложение.</p>
</div>
</body>
</html>"""


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Подтвердите email перед входом")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Аккаунт заблокирован")

    if req.device and req.device.device_fingerprint.strip():
        try:
            await ensure_device_session(
                db,
                user,
                device_name=req.device.device_name,
                device_type=req.device.device_type,
                device_fingerprint=req.device.device_fingerprint,
            )
        except ValueError as e:
            msg = str(e)
            if "лимит" in msg.lower() and "устройств" in msg.lower():
                raise HTTPException(status_code=403, detail=msg)
            logger.warning("login ensure_device_session: %s", e)

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(req.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Недействительный refresh токен")

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь не найден")

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/forgot-password")
async def forgot_password(
    req: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if user:
        token = generate_token()
        user.reset_token = token
        await db.commit()
        base_url = settings.FRONTEND_URL.rstrip("/")
        # Отправка письма в фоне — не блокирует ответ клиенту
        background_tasks.add_task(send_password_reset_email, req.email, token, base_url)
    return {"message": "Если email зарегистрирован, письмо отправлено"}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.reset_token == req.token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Недействительный токен")

    user.password_hash = hash_password(req.new_password)
    user.reset_token = None
    await db.commit()
    return {"message": "Пароль изменён"}


@router.get("/app-reset")
async def app_reset_app_link(token: str, db: AsyncSession = Depends(get_db)):
    """Старые ссылки — редирект на форму смены пароля на сайте."""
    result = await db.execute(select(User).where(User.reset_token == token))
    user = result.scalar_one_or_none()
    if not user:
        return HTMLResponse(_html_page(
            success=False,
            title="Ссылка недействительна",
            message="Токен сброса пароля устарел или уже был использован.",
        ), status_code=400)
    page_url = f"{settings.FRONTEND_URL.rstrip('/')}/api/auth/reset-password-page?token={token}"
    return RedirectResponse(page_url, status_code=302)


@router.get("/reset-password-page", response_class=HTMLResponse)
async def reset_password_page(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Ссылка из письма — смена пароля на сайте (форма остаётся открытой)."""
    result = await db.execute(select(User).where(User.reset_token == token))
    user = result.scalar_one_or_none()
    if not user:
        return HTMLResponse(_html_page(
            success=False,
            title="Ссылка недействительна",
            message="Токен сброса пароля устарел или уже был использован.",
        ), status_code=400)

    token_js = json.dumps(token)
    theme = await load_theme(db)
    reset_title = theme.login_reset_title or "Новый пароль"
    reset_btn = theme.login_reset_button_text or "Сохранить пароль"
    app_brand = (theme.app_name or "Silent VPN").strip() or "Silent VPN"

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{app_brand} — сброс пароля</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#0a0a0a;font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:16px}}
  .card{{background:#111;border:1px solid #222;border-radius:16px;padding:40px 32px;max-width:420px;width:100%;text-align:center}}
  .brand{{color:#fff;font-size:12px;font-weight:700;letter-spacing:3px;margin-bottom:24px;opacity:0.5}}
  h1{{color:#fff;font-size:20px;font-weight:700;margin-bottom:12px}}
  p{{color:#888;font-size:14px;line-height:1.6;margin-bottom:20px}}
  p strong{{color:#ccc}}
  label{{display:block;color:#aaa;font-size:12px;margin-bottom:6px;text-align:left}}
  input{{width:100%;padding:12px;border-radius:10px;border:1px solid #333;background:#1a1a1a;color:#fff;font-size:14px;margin-bottom:12px;box-sizing:border-box}}
  button{{width:100%;padding:14px;border:none;border-radius:10px;background:#fff;color:#000;font-size:14px;font-weight:700;cursor:pointer}}
  .err{{color:#ef4444;font-size:12px;margin-top:8px;min-height:16px;text-align:left}}
  .ok{{color:#22c55e;font-size:14px;margin-top:12px}}
  .hint{{color:#555;font-size:12px;margin-top:16px;line-height:1.5}}
</style>
</head>
<body>
<div class="card">
  <div class="brand">{app_brand.upper()}</div>
  <h1 id="title">{reset_title}</h1>
  <p>Аккаунт: <strong>{user.email}</strong></p>
  <label for="pw">Новый пароль (мин. 8 символов)</label>
  <input type="password" id="pw" minlength="8" autocomplete="new-password">
  <button type="button" id="saveBtn">{reset_btn}</button>
  <div class="err" id="err"></div>
  <div class="ok" id="ok"></div>
  <p class="hint">Смените пароль здесь, затем откройте приложение Silent VPN и войдите с новым паролем.</p>
</div>
<script>
(function(){{
  var token = {token_js};
  document.getElementById('saveBtn').addEventListener('click', async function() {{
    var pw = document.getElementById('pw').value;
    var err = document.getElementById('err');
    var ok = document.getElementById('ok');
    err.textContent = '';
    ok.textContent = '';
    if (pw.length < 8) {{ err.textContent = 'Минимум 8 символов'; return; }}
    try {{
      var res = await fetch('/api/auth/reset-password', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ token: token, new_password: pw }})
      }});
      var data = await res.json().catch(function(){{ return {{}}; }});
      if (!res.ok) {{ err.textContent = data.detail || 'Ошибка'; return; }}
      document.getElementById('title').textContent = 'Пароль сохранён';
      ok.textContent = 'Готово. Откройте приложение Silent VPN и войдите с новым паролем.';
    }} catch (ex) {{ err.textContent = 'Ошибка сети'; }}
  }});
}})();
</script>
</body>
</html>""")


@router.post("/admin/login", response_model=AdminTokenResponse)
async def admin_login(req: AdminLoginRequest):
    if req.login != settings.ADMIN_LOGIN or req.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Неверные данные администратора")
    token = create_access_token("admin", expires_delta=timedelta(hours=12))
    return AdminTokenResponse(access_token=token)
