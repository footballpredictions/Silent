"""Read-only session presence, including per-node GETCONF identities.

WDTT reports remain supported. No peers, subscriptions or connections change.
A short shared snapshot bounds polling cost across clients and API workers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time

logger = logging.getLogger(__name__)
_KEY = "hive:session_presence:v1"
_TTL = 10
_cached_at = 0.0
_cached: dict = {}
_lock = asyncio.Lock()


def online_flags(devices, snapshot: dict) -> dict[str, bool]:
    refs = set(snapshot.get("refs") or [])
    pubs = set(snapshot.get("pubs") or [])
    return {
        str(d.id): bool(d.is_connected) or str(d.id) in refs
        or bool(getattr(d, "device_fingerprint", None) in refs)
        or any(getattr(d, key, None) in pubs for key in ("wg_public_key", "wg_live_public_key"))
        for d in devices
    }


def queen_presence() -> dict:
    # Return only live public keys and exact references, never GETCONF secrets.
    program = """import json,time,subprocess
from pathlib import Path
now=time.time()
rows=subprocess.run(['wg','show','wdtt0','latest-handshakes'],capture_output=True,text=True,timeout=3,check=True).stdout.splitlines()
pubs={a[0] for line in rows if len(a:=line.split())==2 and 0<int(a[1]) and 0<=now-int(a[1])<180}
try: devices=json.loads(Path('/etc/wdtt/passwords.json').read_text()).get('devices',{})
except (OSError,ValueError): devices={}
refs=[str(ref) for ref,d in devices.items() if isinstance(d,dict) and d.get('pub_key') in pubs and not str(ref).startswith('boot:')]
print(json.dumps({'pubs':list(pubs),'refs':refs}))
"""
    try:
        result = subprocess.run(
            ["docker", "exec", "silent-nsenter", "nsenter", "-t", "1", "-m", "-n", "--", "python3", "-c", program],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return json.loads(result.stdout)
    except Exception:
        logger.debug("Queen session presence unavailable", exc_info=True)
        return {"pubs": [], "refs": []}


async def collect_presence() -> dict:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models import HiveCell
    from app.services.hive_service import fetch_worker_cell_load

    async with AsyncSessionLocal() as db:
        cells = list((await db.execute(select(HiveCell).where(
            HiveCell.is_queen == False, HiveCell.status.in_(("active", "draining")),
        ))).scalars().all())
        for c in cells:
            _ = c.id, c.name, c.public_ip, c.api_url, c.api_secret_enc, c.status, c.link_capacity_mbps, c.is_queen
        db.expunge_all()
    results = await asyncio.gather(
        asyncio.to_thread(queen_presence),
        *(fetch_worker_cell_load(c, timeout=2.0, report_incident=False) for c in cells),
        return_exceptions=True,
    )
    refs: set[str] = set()
    pubs: set[str] = set()
    for row in results:
        if not isinstance(row, dict):
            continue
        refs.update(v for v in (row.get("refs") or row.get("wg_live_devices") or []) if isinstance(v, str) and 0 < len(v) <= 256)
        pubs.update(v for v in (row.get("pubs") or row.get("wg_live_pubs") or []) if isinstance(v, str) and len(v) == 44)
    return {"refs": sorted(refs), "pubs": sorted(pubs)}


async def presence_snapshot() -> dict:
    global _cached, _cached_at
    if _cached_at and time.monotonic() - _cached_at < _TTL:
        return _cached
    async with _lock:
        if _cached_at and time.monotonic() - _cached_at < _TTL:
            return _cached
        from app.services.hive_service import _get_shown_redis
        try:
            raw = await asyncio.wait_for(_get_shown_redis().get(_KEY), timeout=0.35)
            if raw:
                decoded = json.loads(raw)
                if not isinstance(decoded, dict) or not all(isinstance(decoded.get(k), list) for k in ("refs", "pubs")):
                    raise ValueError("Invalid presence snapshot")
                _cached = decoded
                _cached_at = time.monotonic()
                return _cached
        except Exception:
            logger.debug("Shared session presence read unavailable")
        _cached = await collect_presence()
        _cached_at = time.monotonic()
        try:
            await asyncio.wait_for(_get_shown_redis().set(_KEY, json.dumps(_cached), ex=_TTL), timeout=0.35)
        except Exception:
            logger.debug("Shared session presence write unavailable")
        return _cached


async def session_online_flags(devices) -> dict[str, bool]:
    try:
        snapshot = await presence_snapshot()
    except Exception:
        logger.debug("Live session presence unavailable", exc_info=True)
        snapshot = {}
    return online_flags(devices, snapshot)
