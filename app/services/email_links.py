"""Ссылки из писем должны жить дольше, чем публичный 443 Улья.

Письмо уходит с одной ссылкой на `FRONTEND_URL`. Когда 443 Улья режут из РФ
(инцидент 2026-09-16), подтвердить регистрацию и сбросить пароль нечем: письмо
пришло, а адрес в нём не открывается. Публичные базы сот (`:9100`) проксируют
`/api/auth/*` на живой Улей. Кнопка в письме — сота (как bootstrap), Улей последним.

Без сети и БД: базы приходят готовым списком (`hive_standby.standby_api_urls`).
"""
from __future__ import annotations

from urllib.parse import urlsplit

MAX_FALLBACK_LINKS = 2

# Туннель и локалхост в письме бесполезны: почту читают вне VPN.
_PRIVATE_PREFIXES = ("10.", "127.", "192.168.", "169.254.", "172.16.", "172.17.",
                     "172.18.", "172.19.", "172.20.", "172.21.", "172.22.",
                     "172.23.", "172.24.", "172.25.", "172.26.", "172.27.",
                     "172.28.", "172.29.", "172.30.", "172.31.")


def is_public_email_base(base: str) -> bool:
    parts = urlsplit((base or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower()
    if host in ("localhost", "::1") or host.startswith(_PRIVATE_PREFIXES):
        return False
    return True


def _host_of(base: str) -> str:
    return (urlsplit(base).hostname or "").lower()


def email_action_links(
    path: str,
    token: str,
    primary_base: str,
    fallback_bases: list[str] | tuple[str, ...] | None = None,
    *,
    max_fallbacks: int = MAX_FALLBACK_LINKS,
    exclude_hosts: list[str] | tuple[str, ...] = (),
    prefer_standby_first: bool = True,
) -> list[str]:
    """Кнопка в письме — живая сота :9100 (тот же вход, что bootstrap).

    443 Улья из РФ часто мёртв: ссылка на nip.io в кнопке не открывается,
    хотя регистрация уже прошла через соту. Сота проксирует /api/auth/* на Улей.
    Улей в списке последним — на случай, если 443 жив.
    Один хост — одна ссылка (второй порт той же машины слот не занимает).
    """
    if not token or not is_public_email_base(primary_base):
        return []
    rel = f"/{path.lstrip('/')}?token={token}"
    primary = primary_base.strip().rstrip("/")
    hive_hosts = {_host_of(primary)} | {h.strip().lower() for h in exclude_hosts if h}

    standby: list[str] = []
    used_hosts: set[str] = set()
    for base in fallback_bases or []:
        if len(standby) >= max(0, max_fallbacks):
            break
        clean = (base or "").strip().rstrip("/")
        if not clean or not is_public_email_base(clean):
            continue
        host = _host_of(clean)
        if host in hive_hosts or host in used_hosts:
            continue
        used_hosts.add(host)
        standby.append(clean)

    if prefer_standby_first and standby:
        return [f"{b}{rel}" for b in standby] + [f"{primary}{rel}"]
    return [f"{primary}{rel}"] + [f"{b}{rel}" for b in standby]
