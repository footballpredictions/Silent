from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
import secrets


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # App
    APP_NAME: str = "Silent VPN"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = secrets.token_hex(32)

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://silent:silent_pass@db:5432/silent_vpn"
    REDIS_URL: str = "redis://redis:6379"

    # JWT
    JWT_SECRET: str = secrets.token_hex(32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 дней
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Email
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    EMAIL_FROM: str = "noreply@silent-vpn.ru"
    EMAIL_FROM_NAME: str = "Silent VPN"
    FRONTEND_URL: str = "https://132-243-234-162.nip.io"

    # YuMoney
    YUMONEY_WALLET_1: str = ""
    YUMONEY_WALLET_2: str = ""
    YUMONEY_SECRET: str = ""

    # Admin
    ADMIN_LOGIN: str = "admin"
    ADMIN_PASSWORD: str = "change_me_123"

    # VK AI Assistant (Android client token for calls.create / TURN hashes)
    VK_LOGIN: str = ""
    VK_PASSWORD: str = ""
    # Токен Android-клиента (6287487): vk1.a.... — приоритет над OAuth/БД
    VK_AGENT_ACCESS_TOKEN: str = ""
    VK_CLIENT_IDS: List[int] = [6287487, 8202606]

    # VK Community bot (config delivery via messages)
    VK_GROUP_ID: int = 0
    VK_COMMUNITY_TOKEN: str = ""

    # VK ID (user linking)
    VK_ID_APP_ID: int = 0
    VK_ID_CLIENT_SECRET: str = ""
    VK_ID_REDIRECT_URI: str = "https://132-243-234-162.nip.io/api/auth/vk/callback"
    VK_MESSAGES_REDIRECT_URI: str = "https://132-243-234-162.nip.io/api/auth/vk/messages-callback"
    VK_BOT_WRITE_URL: str = "https://vk.com/write-239092728"

    # VPN Server
    VPN_SERVER_IP: str = ""
    VPN_SERVER_PORT: int = 56000
    WG_PORT: int = 56001
    WG_SUBNET: str = "10.66.66.0/24"
    MAX_DEVICES_PER_USER: int = 3
    WDTT_MASTER_PASSWORD: str = ""
    # Shared secret for server-to-server online reports from wdtt-server
    INTERNAL_API_SECRET: str = ""
    WG_SERVER_PUBLIC_KEY: str = ""
    SESSION_ONLINE_TIMEOUT_MINUTES: int = 10
    SESSION_MAX_AGE_DAYS: int = 7
    SESSION_IDLE_HOURS: int = 6
    TRIAL_DAYS: int = 3

    # Subscription prices
    PRICE_MONTHLY: float = 199.0
    PRICE_QUARTERLY: float = 499.0
    PRICE_YEARLY: float = 1499.0

    # CORS
    ALLOWED_ORIGINS: List[str] = ["*"]


settings = Settings()
