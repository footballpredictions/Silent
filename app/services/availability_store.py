"""Хранилище отчётов агента доступности и клиентских репортов о сбоях.

Отчёты и репорты лежат в Postgres, а не в памяти: `uvicorn --workers N` держит
несколько процессов, и агент-лидер должен видеть репорты, пришедшие в другой воркер.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import AppSetting

logger = logging.getLogger(__name__)

REPORTS_KEEP = 300
CLIENT_REPORTS_KEEP_HOURS = 48
CLIENT_REPORT_MAX_ROWS = 20000
SHORT_TUNNEL_SEC = 45
# Репорт старше срока хранения бесполезен: он не попадёт ни в одно окно агрегации
# и будет удалён следующей же чисткой.
CLIENT_REPORT_MAX_AGE_SEC = CLIENT_REPORTS_KEEP_HOURS * 3600

SETTING_ENABLED = "availability_agent_enabled"
SETTING_INTERVAL = "availability_agent_interval_sec"
SETTING_RU_NODES = "availability_agent_ru_nodes"
SETTING_WORLD_NODES = "availability_agent_world_nodes"
SETTING_EXTERNAL = "availability_agent_external_enabled"
SETTING_LAST_RUN = "availability_agent_last_run"
SETTING_LAST_STATUS = "availability_agent_last_status"
# Память о том, о чём уже сообщали в «Инциденты»: иначе одна и та же блокировка
# писалась бы в журнал каждый цикл и вытесняла остальные события.
SETTING_INCIDENT_STATE = "availability_agent_incident_state"
INCIDENT_STATE_MAX_KEYS = 40


def _defaults() -> dict[str, Any]:
    from app.config import settings

    return {
        SETTING_ENABLED: bool(settings.AVAILABILITY_AGENT_ENABLED),
        SETTING_INTERVAL: int(settings.AVAILABILITY_AGENT_INTERVAL_SEC),
        SETTING_RU_NODES: int(settings.AVAILABILITY_RU_NODES),
        SETTING_WORLD_NODES: int(settings.AVAILABILITY_WORLD_NODES),
        SETTING_EXTERNAL: bool(settings.AVAILABILITY_EXTERNAL_ENABLED),
    }

_INSERT_REPORT = text(
    "INSERT INTO availability_reports (ts, status, summary, report_json) "
    "VALUES (:ts, :status, :summary, :report_json)"
)
_SELECT_LATEST = text(
    "SELECT ts, status, summary, report_json FROM availability_reports "
    "ORDER BY ts DESC, id DESC LIMIT 1"
)
_SELECT_HISTORY = text(
    "SELECT ts, status, summary FROM availability_reports ORDER BY ts DESC, id DESC LIMIT :limit"
)
_PRUNE_REPORTS = text(
    "DELETE FROM availability_reports WHERE id NOT IN "
    "(SELECT id FROM availability_reports ORDER BY ts DESC, id DESC LIMIT :keep)"
)

_INSERT_CLIENT = text(
    """
    INSERT INTO availability_client_reports (
        ts, stage, transport, network_type, carrier, server_slot,
        tunnel_uptime_sec, platform, app_version, detail
    ) VALUES (
        :ts, :stage, :transport, :network_type, :carrier, :server_slot,
        :tunnel_uptime_sec, :platform, :app_version, :detail
    )
    """
)
_SELECT_CLIENT_WINDOW = text(
    """
    SELECT stage, transport, network_type, carrier, server_slot, tunnel_uptime_sec
    FROM availability_client_reports
    WHERE ts >= :since
    ORDER BY ts DESC
    LIMIT 5000
    """
)
_PRUNE_CLIENT = text("DELETE FROM availability_client_reports WHERE ts < :cutoff")
# Жёсткий потолок строк: эндпоинт публичный, и даже с rate limit таблица не должна расти.
_PRUNE_CLIENT_CAP = text(
    "DELETE FROM availability_client_reports WHERE id NOT IN "
    "(SELECT id FROM availability_client_reports ORDER BY ts DESC, id DESC LIMIT :keep)"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _get(db: AsyncSession, key: str) -> str | None:
    row = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    return row.value if row else None


async def _set(db: AsyncSession, key: str, value: str) -> None:
    row = (await db.execute(select(AppSetting).where(AppSetting.key == key))).scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _as_int(raw: str | None, default: int, *, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(str(raw).strip())))
    except (TypeError, ValueError):
        return default


async def load_settings(db: AsyncSession) -> dict[str, Any]:
    defaults = _defaults()
    return {
        "enabled": _as_bool(await _get(db, SETTING_ENABLED), bool(defaults[SETTING_ENABLED])),
        "interval_sec": _as_int(
            await _get(db, SETTING_INTERVAL), int(defaults[SETTING_INTERVAL]), lo=300, hi=21600
        ),
        "ru_nodes": _as_int(
            await _get(db, SETTING_RU_NODES), int(defaults[SETTING_RU_NODES]), lo=1, hi=12
        ),
        "world_nodes": _as_int(
            await _get(db, SETTING_WORLD_NODES), int(defaults[SETTING_WORLD_NODES]), lo=0, hi=6
        ),
        "external_enabled": _as_bool(
            await _get(db, SETTING_EXTERNAL), bool(defaults[SETTING_EXTERNAL])
        ),
        "last_run": await _get(db, SETTING_LAST_RUN),
        "last_status": await _get(db, SETTING_LAST_STATUS),
    }


async def save_settings(db: AsyncSession, patch: dict[str, Any]) -> dict[str, Any]:
    if "enabled" in patch:
        await _set(db, SETTING_ENABLED, "true" if patch["enabled"] else "false")
    if "external_enabled" in patch:
        await _set(db, SETTING_EXTERNAL, "true" if patch["external_enabled"] else "false")
    if "interval_sec" in patch:
        await _set(db, SETTING_INTERVAL, str(_as_int(str(patch["interval_sec"]), 1800, lo=300, hi=21600)))
    if "ru_nodes" in patch:
        await _set(db, SETTING_RU_NODES, str(_as_int(str(patch["ru_nodes"]), 4, lo=1, hi=8)))
    if "world_nodes" in patch:
        await _set(db, SETTING_WORLD_NODES, str(_as_int(str(patch["world_nodes"]), 2, lo=0, hi=6)))
    await db.commit()
    return await load_settings(db)


async def mark_run(status: str) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await _set(db, SETTING_LAST_RUN, _utc_now().isoformat())
            await _set(db, SETTING_LAST_STATUS, (status or "unknown")[:32])
            await db.commit()
    except Exception as e:
        logger.warning("availability: не удалось записать метку запуска: %s", e)


async def load_incident_state() -> dict[str, dict[str, Any]]:
    """Что уже уходило в журнал инцидентов: `{signature: {seen, notified_at}}`."""
    try:
        async with AsyncSessionLocal() as db:
            raw = await _get(db, SETTING_INCIDENT_STATE)
    except Exception as e:
        logger.warning("availability: состояние инцидентов не прочитано: %s", e)
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def save_incident_state(state: dict[str, dict[str, Any]]) -> None:
    trimmed = dict(list(state.items())[:INCIDENT_STATE_MAX_KEYS])
    try:
        async with AsyncSessionLocal() as db:
            await _set(db, SETTING_INCIDENT_STATE, json.dumps(trimmed, ensure_ascii=False))
            await db.commit()
    except Exception as e:
        logger.warning("availability: состояние инцидентов не сохранено: %s", e)


async def save_report(report: dict[str, Any]) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                _INSERT_REPORT,
                {
                    "ts": _utc_now(),
                    "status": str(report.get("status") or "unknown")[:16],
                    "summary": str(report.get("summary") or "")[:1000],
                    "report_json": json.dumps(report, ensure_ascii=False),
                },
            )
            await db.execute(_PRUNE_REPORTS, {"keep": REPORTS_KEEP})
            await db.commit()
    except Exception as e:
        logger.warning("availability: отчёт не сохранён: %s", e)


async def load_latest_report() -> dict[str, Any] | None:
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(_SELECT_LATEST)).mappings().first()
    except Exception as e:
        logger.warning("availability: отчёт не прочитан: %s", e)
        return None
    if not row:
        return None
    try:
        data = json.loads(row.get("report_json") or "{}")
    except Exception:
        data = {}
    if isinstance(data, dict):
        data.setdefault("ts", str(row.get("ts")))
        data.setdefault("status", row.get("status"))
        data.setdefault("summary", row.get("summary"))
        return data
    return None


async def load_history(limit: int = 30) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit or 30), REPORTS_KEEP))
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(_SELECT_HISTORY, {"limit": lim})).mappings().all()
    except Exception as e:
        logger.warning("availability: история не прочитана: %s", e)
        return []
    return [
        {
            "ts": row["ts"].isoformat() if hasattr(row["ts"], "isoformat") else str(row["ts"]),
            "status": row["status"],
            "summary": row["summary"],
        }
        for row in rows
    ]


def event_timestamp(now: datetime, age_sec: int | None) -> datetime | None:
    """Когда отказ произошёл на самом деле, а не когда репорт доехал."""
    from ai.availability_model import client_report_age_sec

    age = client_report_age_sec(age_sec, CLIENT_REPORT_MAX_AGE_SEC)
    if age is None:
        return None
    return now - timedelta(seconds=age)


async def record_client_report(
    db: AsyncSession,
    *,
    stage: str,
    transport: str = "",
    network_type: str = "",
    carrier: str = "",
    server_slot: str = "",
    tunnel_uptime_sec: int | None = None,
    platform: str = "",
    app_version: str = "",
    detail: str = "",
    age_sec: int | None = None,
) -> bool:
    """Клиент сообщил о неудачном подключении. Поля необязательные для старых клиентов.

    Репорт метится временем самого отказа (`now - age_sec`): доставка из очереди
    может случиться через часы, и без поправки отчёт агента врал бы.
    """
    ts = event_timestamp(_utc_now(), age_sec)
    if ts is None:
        return False
    await db.execute(
        _INSERT_CLIENT,
        {
            "ts": ts,
            "stage": (stage or "unknown")[:32],
            "transport": (transport or "")[:16],
            "network_type": (network_type or "")[:16],
            "carrier": (carrier or "")[:64],
            "server_slot": (server_slot or "")[:32],
            "tunnel_uptime_sec": int(tunnel_uptime_sec) if tunnel_uptime_sec is not None else None,
            "platform": (platform or "")[:32],
            "app_version": (app_version or "")[:32],
            "detail": (detail or "")[:400],
        },
    )
    await db.commit()
    return True


def _bump(counter: dict[str, int], key: str) -> None:
    key = (key or "").strip()
    if not key:
        return
    counter[key] = counter.get(key, 0) + 1


async def aggregate_client_reports(window_minutes: int = 30) -> dict[str, dict[str, Any]]:
    """Сводка отказов за окно: по слоту сервера и общая под ключом `*`."""
    window = max(5, min(int(window_minutes or 30), 1440))
    since = _utc_now() - timedelta(minutes=window)
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(_SELECT_CLIENT_WINDOW, {"since": since})).mappings().all()
    except Exception as e:
        logger.warning("availability: клиентские репорты не прочитаны: %s", e)
        return {}

    buckets: dict[str, dict[str, Any]] = {}

    def bucket(key: str) -> dict[str, Any]:
        if key not in buckets:
            buckets[key] = {
                "window_minutes": window,
                "reports": 0,
                "failures": 0,
                "by_stage": {},
                "by_network": {},
                "by_carrier": {},
                "by_transport": {},
                "short_lived_tunnels": 0,
            }
        return buckets[key]

    for row in rows:
        slot = (row.get("server_slot") or "").strip() or "*"
        for key in {slot, "*"}:
            b = bucket(key)
            b["reports"] += 1
            b["failures"] += 1
            _bump(b["by_stage"], row.get("stage") or "")
            _bump(b["by_network"], row.get("network_type") or "")
            _bump(b["by_carrier"], row.get("carrier") or "")
            _bump(b["by_transport"], row.get("transport") or "")
            uptime = row.get("tunnel_uptime_sec")
            if uptime is not None and 0 <= int(uptime) <= SHORT_TUNNEL_SEC:
                b["short_lived_tunnels"] += 1

    return buckets


async def prune_client_reports() -> int:
    cutoff = _utc_now() - timedelta(hours=CLIENT_REPORTS_KEEP_HOURS)
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(_PRUNE_CLIENT, {"cutoff": cutoff})
            capped = await db.execute(_PRUNE_CLIENT_CAP, {"keep": CLIENT_REPORT_MAX_ROWS})
            await db.commit()
            return int(res.rowcount or 0) + int(capped.rowcount or 0)
    except Exception as e:
        logger.warning("availability: чистка клиентских репортов не удалась: %s", e)
        return 0
