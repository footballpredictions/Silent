"""Анти-абуз проверки email при регистрации.

Слои:
1. Жёсткий блок доменов-анонимайзеров / relay (всегда), в т.ч. internet.ru
   (Mail.ru анонимайзер / «красивые» одноразовые адреса).
2. disposable-email-domains (pip) — известные temp-mail домены + субдомены.
3. Запрет plus-alias (user+tag@…) — обход уникальности на Gmail/Yandex/Outlook.
4. Паттерны local-part (по аудиту БД): «точечный» Gmail (a.b.c.d.e),
   рандом Mail.ru-анонимайзера (504c52c1f5lc, trmq1h2hekdm…), trialN@.
5. ALLOWED_EMAIL_DOMAINS — whitelist; пустой список = выключен.
6. canonical_email — для уникальности (Gmail точки / googlemail).
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

_MAILRU_FAMILY = frozenset({
    "mail.ru", "bk.ru", "list.ru", "inbox.ru", "internet.ru",
})

# Провайдеры, где local-part нормализуем для уникальности (точки / googlemail).
_GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})

_PLUS_LOCAL = re.compile(r"\+")
_HEXISH_LOCAL = re.compile(r"^[a-f0-9]{10,20}$")
_RANDOM_ALNUM = re.compile(r"^[a-z0-9]{11,20}$")
_TRIAL_LOCAL = re.compile(r"^trial\d+$")
_VOWELS = set("aeiouy")
_TRIPLE_LETTER = re.compile(r"(.)\1\1")


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


def _vowel_ratio(local: str) -> float:
    letters = [c for c in local if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c in _VOWELS) / len(letters)


def _looks_like_dotted_alias(local: str) -> bool:
    """Gmail «a.b.c.d.e» / массовые точечные алиасы из аудита БД."""
    if local.count(".") < 4:
        return False
    parts = [p for p in local.split(".") if p]
    if len(parts) < 5:
        return False
    # почти все куски короткие (1–3 символа) — не похоже на имя.фамилия
    short = sum(1 for p in parts if len(p) <= 3)
    return short >= len(parts) - 1


def _looks_like_mailru_anonymizer_local(local: str) -> bool:
    """Сгенерированные имена анонимайзера Mail.ru: 504c52c1f5lc, trmq1h2hekdm, 8vjzcomtkhzu."""
    if "." in local or "_" in local or "-" in local:
        return False
    if _TRIAL_LOCAL.match(local):
        return True
    if _HEXISH_LOCAL.match(local):
        return True
    if not _RANDOM_ALNUM.match(local):
        return False
    # тройная буква (stisss…) — чаще ник, не рандом генератора
    if _TRIPLE_LETTER.search(local):
        return False
    has_digit = any(c.isdigit() for c in local)
    has_letter = any(c.isalpha() for c in local)
    if not (has_digit and has_letter):
        return False
    # мало гласных → «рандомная каша», не имя
    return _vowel_ratio(local) < 0.28


def _suspicious_local_error(local: str, domain: str) -> str | None:
    if _looks_like_dotted_alias(local):
        return (
            "Похоже на одноразовый / анонимный адрес (много точек в имени). "
            "Используйте обычный постоянный email."
        )
    if domain in _MAILRU_FAMILY and _looks_like_mailru_anonymizer_local(local):
        return (
            "Похоже на адрес анонимайзера Mail.ru. "
            "Используйте основной ящик (@mail.ru / @bk.ru), не анонимный алиас."
        )
    if _TRIAL_LOCAL.match(local):
        return "Технические адреса вида trial… запрещены. Используйте свой email."
    return None


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


def classify_email_suspicion(email: str) -> str | None:
    """Для отчёта по уже существующим аккаунтам: причина подозрения или None."""
    local, domain = _extract_parts(email)
    if not local or not domain:
        return "invalid"
    if domain == "suahi.com" or _is_disposable(domain):
        return "disposable_domain"
    if _is_hard_blocked(domain) or domain == "internet.ru":
        return "anonymizer_domain"
    if _PLUS_LOCAL.search(local):
        return "plus_alias"
    if _looks_like_dotted_alias(local):
        return "dotted_alias"
    if domain in _MAILRU_FAMILY and _looks_like_mailru_anonymizer_local(local):
        return "mailru_anonymizer_local"
    if _TRIAL_LOCAL.match(local):
        return "trial_local"
    return None


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

    local_err = _suspicious_local_error(local, domain)
    if local_err:
        return local_err

    allowed = settings.ALLOWED_EMAIL_DOMAINS
    if allowed and domain not in {d.strip().lower() for d in allowed}:
        return (
            "Регистрация разрешена только с популярных почтовых сервисов "
            "(Gmail, Mail.ru, Yandex, Outlook, iCloud и др.). Используйте другой email."
        )

    return None
