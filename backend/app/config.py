from pydantic_settings import BaseSettings
from typing import List
import secrets


class Settings(BaseSettings):
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

    # YuMoney
    YUMONEY_WALLET_1: str = ""
    YUMONEY_WALLET_2: str = ""
    YUMONEY_SECRET: str = ""

    # Admin
    ADMIN_LOGIN: str = "admin"
    ADMIN_PASSWORD: str = "change_me_123"

    # VK AI Assistant
    VK_LOGIN: str = ""
    VK_PASSWORD: str = ""
    VK_CLIENT_IDS: List[int] = [6287487, 8202606]

    # VPN Server
    VPN_SERVER_IP: str = ""
    VPN_SERVER_PORT: int = 56000
    WG_PORT: int = 56001
    WG_SUBNET: str = "10.66.66.0/24"
    MAX_DEVICES_PER_USER: int = 3

    # Subscription prices
    PRICE_MONTHLY: float = 199.0
    PRICE_QUARTERLY: float = 499.0
    PRICE_YEARLY: float = 1499.0

    # CORS
    ALLOWED_ORIGINS: List[str] = ["*"]

    # These are used by Docker Compose directly, not by the app
    POSTGRES_PASSWORD: str = "silent_pass"
    REDIS_PASSWORD: str = "silent_redis"
    WDTT_MASTER_PASSWORD: str = "change_this_password"
    WDTT_PORT: int = 56000
    WDTT_WG_PORT: int = 56001

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
