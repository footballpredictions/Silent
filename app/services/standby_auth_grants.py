"""Remember verified user tokens for bounded offline recovery; never store JWTs."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import logging
import time
import uuid

from sqlalchemy import text

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
_seen: dict[str, float] = {}
_tasks: set[asyncio.Task] = set()
_gate: asyncio.Semaphore | None = None
_last_cleanup = 0.0

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS standby_token_grants (
 token_hash VARCHAR(64) PRIMARY KEY,
 user_id UUID NOT NULL,
 token_type VARCHAR(16) NOT NULL,
 expires_at DOUBLE PRECISION NOT NULL,
 seen_at DOUBLE PRECISION NOT NULL
)
"""


async def ensure_schema() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text(SCHEMA_SQL))
        await db.execute(text("CREATE INDEX IF NOT EXISTS ix_standby_grants_user ON standby_token_grants(user_id)"))
        await db.commit()


def remember_verified(token: str, payload: dict) -> None:
    """Called only after the main JWT and active user were verified. Best effort.

    A separate bounded queue/session cannot abort or delay normal authentication.
    Admin JWTs and unverified input never enter this registry.
    """
    try:
        user_id = str(uuid.UUID(str(payload['sub'])))
        kind = payload['type']
        expires = float(payload['exp'])
        if kind not in ('access', 'refresh') or expires <= time.time():
            return
    except (KeyError, TypeError, ValueError, OverflowError):
        return
    digest = sha256(token.encode()).hexdigest()
    now = time.time()
    if _seen.get(digest, 0) > now or len(_tasks) >= 32:
        return
    if len(_seen) > 4096:
        for key in list(_seen):
            if _seen[key] <= now:
                _seen.pop(key, None)
    if len(_seen) > 4096:
        return
    _seen[digest] = now + 300
    task = asyncio.create_task(_persist(digest, user_id, kind, expires, now))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _persist(digest: str, user_id: str, kind: str, expires: float, now: float) -> None:
    global _gate, _last_cleanup
    if _gate is None:
        _gate = asyncio.Semaphore(2)
    try:
        async with _gate, asyncio.timeout(3):
            async with AsyncSessionLocal() as db:
                await db.execute(text("""
                    INSERT INTO standby_token_grants(token_hash,user_id,token_type,expires_at,seen_at)
                    VALUES(:hash,CAST(:uid AS UUID),:kind,:exp,:now)
                    ON CONFLICT(token_hash) DO UPDATE SET seen_at=EXCLUDED.seen_at
                """), {'hash':digest,'uid':user_id,'kind':kind,'exp':expires,'now':now})
                if now-_last_cleanup>3600:
                    await db.execute(text('DELETE FROM standby_token_grants WHERE token_hash IN '
                                          '(SELECT token_hash FROM standby_token_grants WHERE expires_at<:now OR seen_at<:since LIMIT 2000)'),
                                     {'now':now,'since':now-7*86400})
                    _last_cleanup=now
                await db.commit()
    except Exception as exc:
        _seen.pop(digest, None)
        logger.debug('standby grant cache unavailable: %s', type(exc).__name__)


def standby_scope_allows(payload: dict, method: str, path: str) -> bool:
    if not payload.get('standby_until'):
        return True
    if payload.get('standby_scope') != 'vpn-recovery-v1':
        return False
    try:
        if float(payload['standby_until']) <= time.time():
            return False
    except (TypeError, ValueError):
        return False
    if method.upper() == 'GET':
        return path.startswith('/api/vpn/') or path in ('/api/users/me','/api/payments/plans')
    return method.upper() == 'POST' and path in {
        '/api/vpn/device/register', '/api/vpn/connect', '/api/vpn/disconnect',
        '/api/vpn/servers/select', '/api/vpn/reachability', '/api/vpn/hashes/report-failure',
    }
