from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import timedelta
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
from app.services.subscription_service import ensure_trial_subscription
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
    await ensure_trial_subscription(db, user)

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


@router.post("/admin/login", response_model=AdminTokenResponse)
async def admin_login(req: AdminLoginRequest):
    if req.login != settings.ADMIN_LOGIN or req.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Неверные данные администратора")
    token = create_access_token("admin", expires_delta=timedelta(hours=12))
    return AdminTokenResponse(access_token=token)
