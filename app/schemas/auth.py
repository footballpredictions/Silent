from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator
import re


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    referral_or_promo: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен содержать минимум 8 символов")
        return v

    @field_validator("referral_or_promo")
    @classmethod
    def normalize_referral_or_promo(cls, v: str | None) -> str | None:
        if v is None:
            return None
        code = v.strip()
        return code or None


class LoginDeviceInfo(BaseModel):
    device_fingerprint: str
    device_type: str = "android"
    device_name: str = "Android"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    device: LoginDeviceInfo | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class AdminLoginRequest(BaseModel):
    login: str
    password: str


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class VkLinkStartResponse(BaseModel):
    auth_url: str
    bot_url: str = ""


class VkGuestCompleteRequest(BaseModel):
    state: str
    access_token: str
    vk_user_id: int
    bootstrap_hash: str


class VkGuestLinkStartResponse(BaseModel):
    auth_url: str
    state: str


class VkGuestStatusResponse(BaseModel):
    completed: bool = False
    vk_user_id: int | None = None
    bootstrap_hash: str | None = None


class VkAttachRequest(BaseModel):
    vk_user_id: int


class VkLinkStatusResponse(BaseModel):
    linked: bool
    vk_user_id: int | None = None
    linked_at: datetime | None = None
    bot_url: str = ""
    bootstrap_hash: str | None = None
