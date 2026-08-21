"""Кольцевой буфер инцидентов Улья/сот: только падения и ошибки."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.database import AsyncSessionLocal

MAX_INCIDENTS = 800
DEDUP_WINDOW_SEC = 45.0

_incidents: deque[dict[str, Any]] = deque(maxlen=MAX_INCIDENTS)
_last_seen: dict[str, float] = {}
_persist_queue: deque[dict[str, Any]] = deque()
_persist_worker_task: asyncio.Task | None = None

logger = logging.getLogger(__name__)

_INCIDENT_INSERT_SQL = text(
    """
    INSERT INTO hive_incidents (
        ts, severity, source, cell_name, cell_ip, category, hint, message, details, checks_json
    ) VALUES (
        :ts, :severity, :source, :cell_name, :cell_ip, :category, :hint, :message, :details, :checks_json
    )
    """
)

_INCIDENT_SELECT_SQL = text(
    """
    SELECT
        ts, severity, source, cell_name, cell_ip, category, hint, message, details, checks_json
    FROM hive_incidents
    ORDER BY ts DESC, id DESC
    LIMIT :limit
    """
)

_INCIDENT_CLEAR_SQL = text("DELETE FROM hive_incidents")
_META_CLEARED_ENSURE_SQL = text(
    """
    INSERT INTO hive_incident_meta (meta_key, meta_value, updated_at)
    VALUES ('incidents_cleared_at', '1970-01-01T00:00:00+00:00', NOW())
    ON CONFLICT (meta_key) DO NOTHING
    """
)
_META_CLEARED_LOCK_SQL = text(
    "SELECT meta_value FROM hive_incident_meta WHERE meta_key = 'incidents_cleared_at' FOR UPDATE"
)
_META_CLEARED_UPSERT_SQL = text(
    """
    INSERT INTO hive_incident_meta (meta_key, meta_value, updated_at)
    VALUES ('incidents_cleared_at', :value, NOW())
    ON CONFLICT (meta_key)
    DO UPDATE SET meta_value = EXCLUDED.meta_value, updated_at = NOW()
    """
)

_META_UPSERT_SQL = text(
    """
    INSERT INTO hive_incident_meta (meta_key, meta_value, updated_at)
    VALUES ('admin_last_seen_at', :value, NOW())
    ON CONFLICT (meta_key)
    DO UPDATE SET meta_value = EXCLUDED.meta_value, updated_at = NOW()
    """
)

_META_SELECT_SQL = text(
    "SELECT meta_value FROM hive_incident_meta WHERE meta_key = 'admin_last_seen_at'"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _as_utc_dt(value: Any) -> datetime:
    """asyncpg TIMESTAMPTZ ждёт datetime, не ISO-строку — иначе запись молча падает."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return _utc_now()
    else:
        return _utc_now()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _public_ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _utc_now_iso()


def _normalize_msg(msg: str) -> str:
    return " ".join((msg or "").strip().split())[:900]


def should_persist_after_clear(payload_ts: Any, cleared_at: Any) -> bool:
    """Старые события не писать в БД после «Очистить» (очередь другого uvicorn-воркера)."""
    if cleared_at is None or (isinstance(cleared_at, str) and not cleared_at.strip()):
        return True
    return _as_utc_dt(payload_ts) > _as_utc_dt(cleared_at)


def _new_incident_payload(
    *,
    source: str,
    severity: str,
    cell_name: str,
    cell_ip: str,
    category: str,
    hint: str,
    message: str,
    details: str,
    checks: list[str],
) -> dict[str, Any]:
    return {
        "ts": _utc_now_iso(),
        "severity": (severity or "error").lower(),
        "source": source,
        "cell_name": cell_name or None,
        "cell_ip": cell_ip or None,
        "category": category,
        "hint": hint,
        "message": message,
        "details": details,
        "checks": checks,
    }


def _classify(msg: str) -> tuple[str, str, list[str]]:
    raw = (msg or "").lower()
    checks: list[str] = []

    if any(x in raw for x in ("rate limit", "too many attempts", "bad_code", "mfa", "invalid_challenge")):
        checks = [
            "Проверить источник IP и частоту повторов (bruteforce/probing).",
            "При повторе — временно блокировать IP на nginx/фаерволе.",
        ]
        return "security-auth-abuse", "Подозрение на bruteforce/проброс авторизации", checks

    if any(x in raw for x in ("scan", "probe", "bot", "/wp-", "/phpmyadmin", "/admin", "not found", "adminhostguard", "forbidden host")):
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
    payload = _new_incident_payload(
        source=source,
        severity=severity,
        cell_name=cell_name,
        cell_ip=cell_ip,
        category=category,
        hint=hint,
        message=msg,
        details=_normalize_msg(details) if details else "",
        checks=checks,
    )
    _incidents.appendleft(payload)
    _enqueue_persist(payload)
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


def _row_to_public(row: dict[str, Any]) -> dict[str, Any]:
    checks: list[str] = []
    raw_checks = row.get("checks_json") or row.get("checks") or ""
    if isinstance(raw_checks, list):
        checks = [str(x) for x in raw_checks]
    elif raw_checks:
        try:
            parsed = json.loads(raw_checks)
            if isinstance(parsed, list):
                checks = [str(x) for x in parsed]
        except Exception:
            checks = []
    return {
        "ts": _public_ts(row.get("ts")),
        "severity": row.get("severity") or "error",
        "source": row.get("source") or "unknown",
        "cell_name": row.get("cell_name"),
        "cell_ip": row.get("cell_ip"),
        "category": row.get("category") or "unknown",
        "hint": row.get("hint") or "Требуется диагностика",
        "message": row.get("message") or "",
        "details": row.get("details") or "",
        "checks": checks,
    }


def list_incidents(limit: int = 200) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit or 200), MAX_INCIDENTS))
    return [_row_to_public(item) for item in list(_incidents)[:lim]]


async def list_incidents_persisted(limit: int = 200) -> list[dict[str, Any]]:
    """Источник правды — Postgres, чтобы 2 uvicorn worker не прыгали RAM-буферами."""
    lim = max(1, min(int(limit or 200), MAX_INCIDENTS))
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(_INCIDENT_SELECT_SQL, {"limit": lim})).mappings().all()
    except Exception as e:
        logger.warning("Hive incidents list from DB failed: %s", e)
        return list_incidents(lim)
    items = [_row_to_public(dict(row)) for row in rows]
    return items


def clear_incidents() -> None:
    _incidents.clear()
    _last_seen.clear()
    _persist_queue.clear()


def _enqueue_persist(payload: dict[str, Any]) -> None:
    global _persist_worker_task
    _persist_queue.append(payload)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Нет event-loop (редкий синхронный контекст) — инцидент остаётся в RAM-логе.
        return
    if _persist_worker_task is None or _persist_worker_task.done():
        _persist_worker_task = loop.create_task(_persist_worker())


async def _persist_worker() -> None:
    while _persist_queue:
        payload = _persist_queue.popleft()
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(_META_CLEARED_ENSURE_SQL)
                row = (await db.execute(_META_CLEARED_LOCK_SQL)).mappings().first()
                cleared_at = (row or {}).get("meta_value") if row else None
                if not should_persist_after_clear(payload.get("ts"), cleared_at):
                    await db.rollback()
                    continue
                await db.execute(
                    _INCIDENT_INSERT_SQL,
                    {
                        "ts": _as_utc_dt(payload.get("ts")),
                        "severity": payload.get("severity"),
                        "source": payload.get("source"),
                        "cell_name": payload.get("cell_name"),
                        "cell_ip": payload.get("cell_ip"),
                        "category": payload.get("category"),
                        "hint": payload.get("hint"),
                        "message": payload.get("message"),
                        "details": payload.get("details") or "",
                        "checks_json": json.dumps(payload.get("checks") or [], ensure_ascii=False),
                    },
                )
                await db.commit()
        except Exception as e:
            logger.warning("Hive incidents persist failed: %s", e)


async def load_persisted_incidents(limit: int = MAX_INCIDENTS) -> None:
    lim = max(1, min(int(limit or MAX_INCIDENTS), MAX_INCIDENTS))
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(_INCIDENT_SELECT_SQL, {"limit": lim})
            ).mappings().all()
    except Exception as e:
        logger.warning("Hive incidents bootstrap skipped: %s", e)
        return

    _incidents.clear()
    for row in rows:
        _incidents.append(_row_to_public(dict(row)))


async def clear_persisted_incidents() -> None:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(_META_CLEARED_UPSERT_SQL, {"value": _utc_now_iso()})
            await db.execute(_INCIDENT_CLEAR_SQL)
            await db.commit()
    except Exception as e:
        logger.warning("Hive incidents clear in DB failed: %s", e)


async def mark_admin_incidents_seen() -> str:
    seen_at = _utc_now_iso()
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(_META_UPSERT_SQL, {"value": seen_at})
            await db.commit()
    except Exception as e:
        logger.warning("Hive incidents mark-seen failed: %s", e)
    return seen_at


async def get_admin_incidents_seen_at() -> str | None:
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(_META_SELECT_SQL)).mappings().first()
    except Exception as e:
        logger.warning("Hive incidents get-seen failed: %s", e)
        return None
    if not row:
        return None
    value = (row.get("meta_value") or "").strip()
    return value or None
