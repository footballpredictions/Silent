import uuid
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.core.security import decode_token
from app.models import User
from app.services.admin_auth_service import get_valid_session

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    from app.services.standby_auth_grants import remember_verified, standby_scope_allows
    if payload.get("standby_until") and not standby_scope_allows(
        payload, request.method if request else "", request.url.path if request else "",
    ):
        raise HTTPException(status_code=403, detail="Резервный сеанс разрешает подключение VPN и чтение профиля. Войдите снова для изменения аккаунта.")
    if payload.get('standby_until') and request and request.url.path == '/api/vpn/device/register':
        from app.models import Device
        body = await request.json()
        known = await db.scalar(select(Device.id).where(
            Device.user_id == user.id, Device.is_active == True,
            Device.device_fingerprint == body.get('device_fingerprint',''),
        ))
        if known is None:
            raise HTTPException(status_code=403, detail='Для нового устройства войдите снова после восстановления Улья')
    remember_verified(credentials.credentials, payload)

    return user


async def get_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_verified:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email not verified")
    return user


async def get_admin_credentials(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> bool:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin auth required")
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("sub") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    # Legacy JWTs without jti are rejected — force re-login with MFA/session
    session = await get_valid_session(db, payload.get("jti"))
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin session expired")
    return True


async def get_admin_session_jti(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str | None:
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("sub") != "admin":
        return None
    return payload.get("jti")
