"""Admin-debug quality reports (пассивная скорость с Android debug).

Таблица создаётся fail-safe при старте API. Не-админы сюда не пишут.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

KEEP_DAYS = 14
MAX_ROWS = 5000

_ENSURE = text(
    """
    CREATE TABLE IF NOT EXISTS admin_quality_reports (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        user_id UUID,
        email VARCHAR(255) NOT NULL DEFAULT '',
        verdict VARCHAR(32) NOT NULL DEFAULT '',
        likely_cause VARCHAR(128) NOT NULL DEFAULT '',
        down_mbps DOUBLE PRECISION,
        up_mbps DOUBLE PRECISION,
        network_type VARCHAR(16) NOT NULL DEFAULT '',
        carrier VARCHAR(64) NOT NULL DEFAULT '',
        server_slot VARCHAR(32) NOT NULL DEFAULT '',
        tunnel_rtt_ms DOUBLE PRECISION,
        platform VARCHAR(32) NOT NULL DEFAULT '',
        app_version VARCHAR(32) NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL DEFAULT ''
    )
    """
)
_IX = text(
    "CREATE INDEX IF NOT EXISTS ix_admin_quality_reports_ts "
    "ON admin_quality_reports (ts DESC)"
)

_INSERT = text(
    """
    INSERT INTO admin_quality_reports (
        ts, user_id, email, verdict, likely_cause, down_mbps, up_mbps,
        network_type, carrier, server_slot, tunnel_rtt_ms,
        platform, app_version, detail, payload_json
    ) VALUES (
        :ts, :user_id, :email, :verdict, :likely_cause, :down_mbps, :up_mbps,
        :network_type, :carrier, :server_slot, :tunnel_rtt_ms,
        :platform, :app_version, :detail, :payload_json
    )
    """
)

_PRUNE = text(
    """
    DELETE FROM admin_quality_reports
    WHERE ts < :cutoff
       OR id NOT IN (
            SELECT id FROM admin_quality_reports ORDER BY ts DESC LIMIT :keep
       )
    """
)

_SELECT_RECENT = text(
    """
    SELECT id, ts, email, verdict, likely_cause, down_mbps, up_mbps,
           network_type, carrier, server_slot, tunnel_rtt_ms,
           platform, app_version, detail
    FROM admin_quality_reports
    ORDER BY ts DESC
    LIMIT :limit
    """
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_quality_table(conn) -> None:
    await conn.execute(_ENSURE)
    await conn.execute(_IX)


async def record_quality_report(
    db: AsyncSession,
    *,
    user_id: Any,
    email: str,
    verdict: str,
    likely_cause: str = "",
    down_mbps: float | None = None,
    up_mbps: float | None = None,
    network_type: str = "",
    carrier: str = "",
    server_slot: str = "",
    tunnel_rtt_ms: float | None = None,
    platform: str = "",
    app_version: str = "",
    detail: str = "",
    age_sec: int | None = None,
    payload_json: str = "",
) -> bool:
    now = _utc_now()
    ts = now
    if age_sec is not None and age_sec >= 0:
        if age_sec > KEEP_DAYS * 86400:
            return False
        ts = now - timedelta(seconds=int(age_sec))
    try:
        await db.execute(
            _INSERT,
            {
                "ts": ts,
                "user_id": user_id,
                "email": (email or "")[:255],
                "verdict": (verdict or "")[:32],
                "likely_cause": (likely_cause or "")[:128],
                "down_mbps": down_mbps,
                "up_mbps": up_mbps,
                "network_type": (network_type or "")[:16],
                "carrier": (carrier or "")[:64],
                "server_slot": (server_slot or "")[:32],
                "tunnel_rtt_ms": tunnel_rtt_ms,
                "platform": (platform or "")[:32],
                "app_version": (app_version or "")[:32],
                "detail": (detail or "")[:400],
                "payload_json": (payload_json or "")[:8000],
            },
        )
        await db.execute(
            _PRUNE,
            {"cutoff": now - timedelta(days=KEEP_DAYS), "keep": MAX_ROWS},
        )
        await db.commit()
        return True
    except Exception as e:
        logger.warning("quality report not saved: %s", e)
        await db.rollback()
        return False


async def list_recent(limit: int = 50) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit or 50), 200))
    try:
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(_SELECT_RECENT, {"limit": lim})).mappings().all()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "ts": r["ts"].isoformat() if r["ts"] else None,
                    "email": r["email"],
                    "verdict": r["verdict"],
                    "likely_cause": r["likely_cause"],
                    "down_mbps": r["down_mbps"],
                    "up_mbps": r["up_mbps"],
                    "network_type": r["network_type"],
                    "carrier": r["carrier"],
                    "server_slot": r["server_slot"],
                    "tunnel_rtt_ms": r["tunnel_rtt_ms"],
                    "platform": r["platform"],
                    "app_version": r["app_version"],
                    "detail": r["detail"],
                }
            )
        return out
    except Exception as e:
        logger.warning("quality list failed: %s", e)
        return []


def payload_preview(raw: str) -> str:
    if not raw:
        return ""
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False)[:200]
    except Exception:
        return raw[:200]
