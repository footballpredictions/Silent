"""Кольцевой буфер инцидентов Улья/сот: только падения и ошибки."""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

MAX_INCIDENTS = 800
DEDUP_WINDOW_SEC = 45.0

_incidents: deque[dict[str, Any]] = deque(maxlen=MAX_INCIDENTS)
_last_seen: dict[str, float] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_msg(msg: str) -> str:
    return " ".join((msg or "").strip().split())[:900]


def _classify(msg: str) -> tuple[str, str, list[str]]:
    raw = (msg or "").lower()
    checks: list[str] = []

    if any(x in raw for x in ("rate limit", "too many attempts", "bad_code", "mfa", "invalid_challenge", "admin host guard", "forbidden host")):
        checks = [
            "Проверить источник IP и частоту повторов (bruteforce/probing).",
            "При повторе — временно блокировать IP на nginx/фаерволе.",
        ]
        return "security-auth-abuse", "Подозрение на bruteforce/проброс авторизации", checks

    if any(x in raw for x in ("scan", "probe", "bot", "/wp-", "/phpmyadmin", "/admin", "not found")):
        checks = [
            "Проверить access.log nginx и user-agent/ip повторов.",
            "Ограничить доступ по IP/гео или ужесточить rate limits.",
        ]
        return "security-probing", "Подозрение на сканирование/пробинг", checks

    if any(x in raw for x in ("401", "403", "unauthor", "forbidden", "secret", "password")):
        checks = [
            "Проверить секрет cell-agent (X-Cell-Agent-Secret) и api_url.",
            "Сверить, не менялся ли пароль/секрет после авто-апдейта.",
        ]
        return "auth", "Неверный секрет/доступ к agent", checks

    if any(x in raw for x in ("timed out", "timeout", "read timeout", "connect timeout")):
        checks = [
            "Проверить RTT/потери между Ульем и сотой.",
            "Проверить, не режутся ли порты/соединения DPI/фаерволом.",
        ]
        return "network-timeout", "Сеть/таймаут (в т.ч. DPI или блокировка)", checks

    if any(x in raw for x in ("name or service not known", "temporary failure in name resolution", "dns", "resolve")):
        checks = [
            "Проверить DNS на Улье и на соте.",
            "Проверить блокировки доменов у провайдера.",
        ]
        return "dns", "Проблема DNS/резолва", checks

    if any(x in raw for x in ("connection refused", "connection reset", "no route to host", "econnreset", "econnrefused")):
        checks = [
            "Проверить, что cell-agent жив и слушает порт.",
            "Проверить блокировки по IP/порту у провайдера и local firewall.",
        ]
        return "port-ip-block", "Порт/IP недоступен или процесс упал", checks

    if any(x in raw for x in ("out of memory", "oom", "cpu", "memory", "overload", "overloaded", "full")):
        checks = [
            "Проверить CPU/RAM и лимиты systemd/docker.",
            "Проверить churn перезапусков и аномальный рост процессов.",
        ]
        return "resource", "Перегрузка ресурсов", checks

    checks = [
        "Сверить журнал systemd на соте и логи backend-api.",
        "Проверить сетевые блокировки (порт/домен/IP) и ретраи.",
    ]
    return "unknown", "Требуется ручная диагностика", checks


def push_incident(
    *,
    source: str,
    message: str,
    severity: str = "error",
    cell_name: str = "",
    cell_ip: str = "",
    details: str = "",
) -> bool:
    msg = _normalize_msg(message)
    if not msg:
        return False

    dedup_key = f"{source}|{cell_name}|{cell_ip}|{msg[:220]}"
    now = time.time()
    prev = _last_seen.get(dedup_key)
    if prev and (now - prev) < DEDUP_WINDOW_SEC:
        return False
    _last_seen[dedup_key] = now

    category, hint, checks = _classify(f"{msg} {details}")
    _incidents.appendleft(
        {
            "ts": _utc_now_iso(),
            "severity": (severity or "error").lower(),
            "source": source,
            "cell_name": cell_name or None,
            "cell_ip": cell_ip or None,
            "category": category,
            "hint": hint,
            "message": msg,
            "details": _normalize_msg(details) if details else "",
            "checks": checks,
        }
    )
    return True


def push_security_event(
    *,
    source: str,
    message: str,
    severity: str = "warning",
    client_ip: str = "",
    details: str = "",
) -> bool:
    text = message
    if client_ip:
        text = f"{message} ip={client_ip}"
    return push_incident(
        source=f"security.{source}",
        severity=severity,
        message=text,
        details=details,
    )


def list_incidents(limit: int = 200) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit or 200), MAX_INCIDENTS))
    return list(_incidents)[:lim]


def clear_incidents() -> None:
    _incidents.clear()
    _last_seen.clear()
