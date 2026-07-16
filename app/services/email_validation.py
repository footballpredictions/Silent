"""Анти-абуз проверки email при регистрации: блок временных почт + whitelist доменов.

Два независимых слоя защиты:
1. disposable-блоклист (пакет disposable-email-domains, тысячи известных
   временных/одноразовых доменов типа suahi.com, mailinator.com и т.п.) —
   работает всегда, обновляется через pip при деплое.
2. ALLOWED_EMAIL_DOMAINS (config.py / .env) — если список не пуст, разрешены
   только домены из него (строгий whitelist). Пусто — whitelist выключен.
"""
from disposable_email_domains import blocklist as DISPOSABLE_DOMAINS

from app.config import settings


def _extract_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower().rstrip(".")


def _is_disposable(domain: str) -> bool:
    """Проверяет домен и все его род. суффиксы (защита от поддоменов вида
    x1.mailinator.com, которые крутят разовые сервисы)."""
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in DISPOSABLE_DOMAINS:
            return True
    return False


def validate_registration_email_domain(email: str) -> str | None:
    """Возвращает текст ошибки, если домен email запрещён для регистрации,
    иначе None (домен разрешён)."""
    domain = _extract_domain(email)
    if not domain:
        return "Некорректный email"

    if _is_disposable(domain):
        return "Временные / одноразовые почтовые адреса запрещены. Используйте постоянный email."

    allowed = settings.ALLOWED_EMAIL_DOMAINS
    if allowed and domain not in {d.strip().lower() for d in allowed}:
        return (
            "Регистрация разрешена только с популярных почтовых сервисов "
            "(Gmail, Mail.ru, Yandex, Outlook, iCloud и др.). Используйте другой email."
        )

    return None
