"""Анти-абуз проверки email при регистрации.

Слои:
1. Жёсткий блок доменов-анонимайзеров / relay (всегда), в т.ч. internet.ru
   (Mail.ru анонимайзер / «красивые» одноразовые адреса).
2. disposable-email-domains (pip) — известные temp-mail домены + субдомены.
3. Запрет plus-alias (user+tag@…) — обход уникальности на Gmail/Yandex/Outlook.
4. ALLOWED_EMAIL_DOMAINS — whitelist; пустой список = выключен.
5. canonical_email — для уникальности (Gmail точки / googlemail).
"""
from __future__ import annotations

import re

from disposable_email_domains import blocklist as DISPOSABLE_DOMAINS

from app.config import settings

# Домены анонимайзеров / hide-my-email / relay — даже если попали в whitelist.
BLOCKED_EMAIL_DOMAINS: frozenset[str] = frozenset({
    # Mail.ru: анонимайзер и «красивые» адреса часто на internet.ru
    "internet.ru",
    # Apple Hide My Email
    "privaterelay.appleid.com",
    # DuckDuckGo Email Protection
    "duck.com",
    # Firefox Relay
    "mozmail.com",
    # SimpleLogin / AnonAddy / Addy
    "simplelogin.com",
    "simplelogin.co",
    "aleeas.com",
    "slmail.me",
    "anonaddy.me",
    "anonaddy.com",
    "addy.io",
    # Other common relays / burners that slip past disposable lists
    "passmail.net",
    "passinbox.com",
    "relay.firefox.com",
})

# Провайдеры, где local-part нормализуем для уникальности (точки / googlemail).
_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})

_PLUS_LOCAL = re.compile(r"\+")


def _extract_parts(email: str) -> tuple[str, str]:
    raw = (email or "").strip().lower()
    if "@" not in raw:
        return "", ""
    local, domain = raw.rsplit("@", 1)
    return local.strip(), domain.strip().rstrip(".")


def _extract_domain(email: str) -> str:
    return _extract_parts(email)[1]


def _domain_or_parent_in(domain: str, block: frozenset[str] | set[str]) -> bool:
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in block:
            return True
    return False


def _is_disposable(domain: str) -> bool:
    return _domain_or_parent_in(domain, DISPOSABLE_DOMAINS)


def _is_hard_blocked(domain: str) -> bool:
    return _domain_or_parent_in(domain, BLOCKED_EMAIL_DOMAINS)


def canonical_email(email: str) -> str:
    """Канонический вид для проверки «тот же ящик».

    - lower
    - отрезает +tag
    - Gmail: убирает точки, googlemail → gmail.com
    """
    local, domain = _extract_parts(email)
    if not local or not domain:
        return (email or "").strip().lower()

    if _PLUS_LOCAL.search(local):
        local = local.split("+", 1)[0]

    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"

    return f"{local}@{domain}"


def validate_registration_email_domain(email: str) -> str | None:
    """Текст ошибки, если email нельзя использовать при регистрации; иначе None."""
    local, domain = _extract_parts(email)
    if not local or not domain:
        return "Некорректный email"

    if _PLUS_LOCAL.search(local):
        return (
            "Адреса с «+» (алиасы вроде name+tag@gmail.com) запрещены. "
            "Укажите основной email без плюса."
        )

    if _is_hard_blocked(domain):
        return (
            "Анонимные / одноразовые почтовые адреса запрещены "
            "(анонимайзер Mail.ru, Hide My Email и аналоги). "
            "Используйте обычный постоянный email."
        )

    if _is_disposable(domain):
        return "Временные / одноразовые почтовые адреса запрещены. Используйте постоянный email."

    allowed = settings.ALLOWED_EMAIL_DOMAINS
    if allowed and domain not in {d.strip().lower() for d in allowed}:
        return (
            "Регистрация разрешена только с популярных почтовых сервисов "
            "(Gmail, Mail.ru, Yandex, Outlook, iCloud и др.). Используйте другой email."
        )

    return None
