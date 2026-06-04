import uuid
from pydantic import BaseModel
from typing import Optional


class DeviceRegisterRequest(BaseModel):
    device_name: str
    device_type: str  # android, ios, pc
    device_fingerprint: str
    wg_public_key: Optional[str] = None
    bootstrap_hash: Optional[str] = None


class HashRefreshRequest(BaseModel):
    device_fingerprint: str


class BootstrapConfigRequest(BaseModel):
    """Pre-login VPN config — only bootstrap VK hash, no subscription required."""
    bootstrap_hash: str
    device_type: str  # android, ios, pc
    device_fingerprint: str


class VpnConfigResponse(BaseModel):
    """Complete VPN configuration sent to client."""
    device_id: uuid.UUID
    wg_private_key: str
    wg_address: str
    wg_dns: str
    server_ip: str
    server_port: int
    server_public_key: str
    wdtt_password: str
    vk_hashes: list[str]
    stream_count: int = 9  # libclient -n (workers), not hash count; bootstrap default 9

    model_config = {"from_attributes": True}


class ConnectRequest(BaseModel):
    device_fingerprint: str
    device_type: str
    last_ip: Optional[str] = None


class DisconnectRequest(BaseModel):
    device_fingerprint: str


class AppExclusionRequest(BaseModel):
    device_id: uuid.UUID
    mode: str  # blacklist, whitelist
    packages: list[str]


class ThemeResponse(BaseModel):
    """UI theme data served to all clients."""
    primary_color: str = "#000000"
    background_color: str = "#FFFFFF"
    text_color: str = "#000000"
    accent_color: str = "#1A1A1A"
    toggle_on_color: str = "#000000"
    toggle_off_color: str = "#CCCCCC"
    font_family: str = "Inter"
    logo_url: str = "/static/logo.svg"
    app_name: str = "Silent VPN"
    support_url: str = ""
    privacy_url: str = ""
    terms_url: str = ""
    # Bottom update bar (replaces subscription strip while update is available)
    update_bar_background_color: str = "#2563EB"
    update_bar_text_color: str = "#FFFFFF"
    update_bar_progress_color: str = "#1D4ED8"
    update_bar_label_available: str = "Доступно обновление"
    update_bar_label_downloading: str = "Скачивание…"
