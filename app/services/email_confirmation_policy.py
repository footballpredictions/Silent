"""Skip email confirmation — Extra Settings toggle (default OFF = old behavior)."""
from __future__ import annotations

from typing import Any


def setting_is_on(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("true", "1", "yes", "on")


def register_verification_plan(skip: bool) -> tuple[bool, bool]:
    """Returns (is_verified, send_verification_email)."""
    if skip:
        return True, False
    return False, True


def register_payload(skip: bool) -> dict[str, str]:
    """All values are strings so old Android/iOS Map<String,String> parsers keep working."""
    if skip:
        return {
            "message": "Регистрация успешна. Можно войти.",
            "email_confirmation_required": "false",
        }
    return {
        "message": "Регистрация успешна. Проверьте email для подтверждения.",
        "email_confirmation_required": "true",
    }


def login_allows_unverified(skip: bool, is_verified: bool) -> bool:
    return is_verified or skip


def skip_confirmation(theme_skip: bool, required_flag: Any) -> bool:
    if theme_skip:
        return True
    if required_flag is False:
        return True
    if isinstance(required_flag, str) and required_flag.strip().lower() == "false":
        return True
    return False


def strip_runtime_theme_keys(data: dict) -> dict:
    """skip_email_confirmation is Extra Settings, not a saved ThemePage field."""
    out = dict(data)
    out.pop("skip_email_confirmation", None)
    return out
