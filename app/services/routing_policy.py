"""Shared, versioned domain routing policy. No per-client routing state lives here."""
import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit

from app.services.routing_policy_defaults import DIRECT_DOMAINS, VPN_DOMAINS

KEY = "routing_policy_v1"
MAX_DOMAINS = 2000


def normalize_domains(values: list[str]) -> list[str]:
    if not isinstance(values, list) or len(values) > MAX_DOMAINS:
        raise ValueError("Слишком много сайтов (максимум 2000)")
    result = set()
    for value in values:
        if not isinstance(value, str) or len(value) > 1024:
            raise ValueError("Укажите домен или адрес сайта")
        value = value.strip()
        if not value:
            continue
        if "://" in value:
            url = urlsplit(value)
            if url.scheme not in ("http", "https") or url.username or url.password or not url.hostname:
                raise ValueError("Укажите HTTP/HTTPS адрес сайта")
            value = url.hostname
        value = value.removeprefix("*.").strip(".").lower()
        try:
            value = value.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Некорректный домен") from exc
        try:
            ipaddress.ip_address(value)
        except ValueError:
            pass
        else:
            raise ValueError("Укажите домен, а не IP-адрес")
        if len(value) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                   for label in value.split(".")):
            raise ValueError("Некорректный домен: " + value)
        if "." not in value and value not in ("ru", "su", "xn--p1ai"):
            raise ValueError("Укажите полный домен: " + value)
        result.add(value)
    return sorted(result)


def build_policy(direct_domains: list[str], vpn_domains: list[str]) -> dict:
    payload = {"schema_version": 1, "direct_domains": normalize_domains(direct_domains),
               "vpn_domains": normalize_domains(vpn_domains)}
    payload["revision"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload["refresh_seconds"] = 300
    if len(json.dumps(payload)) > 240000:
        raise ValueError("Список сайтов слишком большой")
    return payload


async def load_policy(db) -> dict:
    from sqlalchemy import select
    from app.models import AppSetting
    row = (await db.execute(select(AppSetting).where(AppSetting.key == KEY))).scalar_one_or_none()
    if row:
        data = json.loads(row.value)
        return build_policy(data["direct_domains"], data["vpn_domains"])
    return build_policy(DIRECT_DOMAINS, VPN_DOMAINS)


async def save_policy(db, direct_domains: list[str], vpn_domains: list[str]) -> dict:
    from sqlalchemy import select
    from app.models import AppSetting
    payload = build_policy(direct_domains, vpn_domains)
    row = (await db.execute(select(AppSetting).where(AppSetting.key == KEY).with_for_update())).scalar_one_or_none()
    if row:
        row.value = json.dumps(payload)
    else:
        db.add(AppSetting(key=KEY, value=json.dumps(payload)))
    await db.commit()
    return payload
