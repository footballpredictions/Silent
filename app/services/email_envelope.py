"""From в письме должен быть доменом SMTP-ящика.

Gmail/Yahoo дропают письма, если SMTP = mail.ru, а From = noreply@silent-vpn.ru
(SPF/DMARC чужого домена). Регистрация при этом 201, в логе может быть «sent».
"""
from __future__ import annotations


def _domain(addr: str) -> str:
    a = (addr or "").strip()
    if "@" not in a:
        return ""
    return a.rsplit("@", 1)[1].lower()


def envelope_from(smtp_user: str, email_from: str) -> str:
    user = (smtp_user or "").strip()
    declared = (email_from or "").strip()
    if user and "@" in user:
        if not declared or "@" not in declared or _domain(declared) != _domain(user):
            return user
    return declared or user


def prefer_cells_first(relays: list | None) -> bool:
    """С Улья smtp.mail.ru:465 часто ENETUNREACH — живые соты шлют сразу."""
    return bool(relays)
