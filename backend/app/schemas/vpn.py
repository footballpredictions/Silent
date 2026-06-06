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


class HashFailureReportRequest(BaseModel):
    """Client reports VK hash / tunnel failure (libclient logs)."""
    hash: str
    error_type: str  # creds_failed | hash_dead | vk_auth_failed | group_failed
    message: str = ""
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
    # Login flow — step 1 (bootstrap hash)
    login_step1_title: str = "Шаг 1 — хеш звонка VK"
    login_step1_instruction: str = (
        "Скопируйте хеш из раздела «Звонки» в приложении ВКонтакте "
        "(на ПК — VK Звонки в браузере). Вставьте хеш или ссылку ниже — "
        "временный канал только для входа или регистрации (2 мин)."
    )
    login_hash_placeholder: str = "Хеш или ссылка на звонок VK"
    login_hash_button_text: str = "Подтвердить"
    login_vk_mobile_url: str = "https://vk.com/calls"
    login_vk_mobile_link_text: str = "ВКонтакте — раздел «Звонки»"
    login_vk_pc_url: str = "https://vk.com/calls"
    login_vk_pc_link_text: str = "VK Звонки в браузере"
    login_link_color: str = "#4680C2"
    # Login flow — step 2 (auth)
    login_step2_title: str = "Шаг 2 — вход или регистрация"
    login_remember_me_label: str = "Запомнить меня"
    login_forgot_password_label: str = "Забыли пароль?"
    login_forgot_title: str = "Восстановление пароля"
    login_forgot_instruction: str = "Введите email — мы отправим ссылку для установки нового пароля."
    login_reset_title: str = "Новый пароль"
    login_reset_button_text: str = "Сохранить пароль"
