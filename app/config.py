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

    # VK Звонки (AI-агент: silent_token → calls.start, app calls.vk.com)
    VK_CALLS_CLIENT_SECRET: str = ""

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

    # Hive (Улей / Соты) — лимит по CPU/RAM/каналу + ёмкость по активным пользователям
    HIVE_CPU_PERCENT_THRESHOLD: float = 85.0
    HIVE_MEM_PERCENT_THRESHOLD: float = 88.0
    HIVE_BANDWIDTH_PERCENT_THRESHOLD: float = 80.0
    HIVE_LINK_CAPACITY_MBPS: float = 1000.0
    HIVE_LINK_TARGET_UTILIZATION_PERCENT: float = 70.0
    HIVE_TARGET_ACTIVE_USER_MBPS: float = 10.0
    HIVE_NETWORK_INTERFACE: str = ""
    HIVE_CELL_HTTP_TIMEOUT_SEC: float = 15.0
    HIVE_PROVISION_SSH_TIMEOUT_SEC: int = 45
    HIVE_PROVISION_STALE_MINUTES: int = 20
    HIVE_CELL_AGENT_PORT: int = 9100
    HIVE_PROVISION_SSH_USER: str = "root"
    HIVE_WDTT_BINARY_PATH: str = ""
    HIVE_REBALANCE_EXISTING_DEVICES: bool = True
    # Адаптивная ёмкость: сэмплы нагрузки и p95 на онлайн-пользователя
    HIVE_CAPACITY_SAMPLE_INTERVAL_SEC: int = 10
    HIVE_CAPACITY_SAMPLE_RETENTION_HOURS: int = 168
    HIVE_CAPACITY_MAX_SAMPLES_PER_CELL: int = 3000
    HIVE_CAPACITY_MIN_SAMPLES: int = 5
    HIVE_CAPACITY_MIN_ONLINE_FOR_LEARN: int = 1
    # Живой лимит: пересчёт от текущего онлайн и CPU/RAM/канала (обновляется каждые 10 с)
    HIVE_CAPACITY_MIN_ONLINE_FOR_LIVE: int = 2
    HIVE_CAPACITY_LIVE_WEIGHT: float = 0.65
    # p50 маржинальной нагрузки (не p95 — иначе один 4K-зритель занижает лимит для всех)
    HIVE_CAPACITY_PERCENTILE: float = 50.0
    # Доля онлайн, которые одновременно качают тяжёлый трафик (остальные — лёгкий фон)
    HIVE_CAPACITY_PEAK_ACTIVE_SHARE: float = 0.10
    HIVE_CELL_CPU_POWER_RATIO_DEFAULT: float = 0.35
    HIVE_CELL_MEM_POWER_RATIO_DEFAULT: float = 0.35
    # Ширина канала сот: по умолчанию 1 Гбит; первая сота — 10 Гбит (см. hive_service.default_link_capacity_for_new_cell)
    HIVE_CELL_DEFAULT_LINK_CAPACITY_MBPS: float = 1000.0
    HIVE_CELL_FIRST_LINK_CAPACITY_MBPS: float = 10000.0
    HIVE_CAPACITY_FALLBACK_CPU_PER_USER: float = 2.0
    HIVE_CAPACITY_FALLBACK_MEM_PER_USER: float = 0.5
    # Гистерезис: пороги «остыл» (~70% от порога перегрузки)
    HIVE_COOLDOWN_CPU_PERCENT: float = 60.0
    HIVE_COOLDOWN_MEM_PERCENT: float = 62.0
    HIVE_COOLDOWN_NET_PERCENT: float = 56.0
    HIVE_COOLDOWN_STABLE_SEC: int = 180
    # Фоновая балансировка офлайн-устройств по CPU/RAM/каналу
    HIVE_REBALANCE_INTERVAL_SEC: int = 30
    HIVE_REBALANCE_ON_HARDWARE: bool = True
    HIVE_REBALANCE_HARDWARE_BATCH: int = 3
    HIVE_REBALANCE_RETURN_BATCH: int = 5
    # На соты только когда онлайн на Улье ≥ этой доли от лимита (CPU/RAM сами по себе не трогают)
    HIVE_SPILL_ONLINE_FRACTION: float = 0.85
    HIVE_SPILL_MIN_QUEEN_ONLINE: int = 0
    # Manifest устройств на соты (не полный дамп БД)
    HIVE_CELL_MANIFEST_SYNC_ENABLED: bool = True
    # Автообновление cell-agent на сотах (SSH из БД), интервал как в админке Улей
    HIVE_CELL_MAINTENANCE_INTERVAL_SEC: int = 10
    HIVE_CELL_AGENT_AUTO_UPGRADE_ENABLED: bool = True
    HIVE_CELL_AGENT_UPGRADE_FAIL_COOLDOWN_SEC: int = 120
    # True = новые VPN на соты при перегрузке Улья; офлайн переносится фоном
    HIVE_WORKER_ROUTING_ENABLED: bool = True
    # Standby / HA: manifest + Git backup (vpnbase)
    HIVE_STANDBY_ENABLED: bool = True
    VPNBASE_GIT_ENABLED: bool = False
    VPNBASE_GIT_TOKEN: str = ""
    VPNBASE_GIT_REPO: str = "silentvpn3/vpnbase"
    VPNBASE_GIT_BRANCH: str = "main"
    VPNBASE_GIT_PATH: str = "hive_export.enc"
    VPNBASE_RAW_URL: str = ""

    # Subscription prices
    PRICE_MONTHLY: float = 199.0
    PRICE_QUARTERLY: float = 499.0
    PRICE_YEARLY: float = 1499.0

    # CORS
    ALLOWED_ORIGINS: List[str] = ["*"]

    # Build agent (OTA nightly + admin «Собрать релиз»)
    BUILD_AGENT_GIT_URL: str = "https://github.com/footballpredictions/Silent.git"
    BUILD_AGENT_TIMEOUT_SEC: int = 3600


settings = Settings()
