"""Сброс online после load-test + bump max_clients для telemost/wb (LTE)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run

REMOTE = r"""
import asyncio, json, urllib.request
from sqlalchemy import delete
from app.database import AsyncSessionLocal
from app.models.olcrtc_room import OlcrtcRoomSticky
from app.services.olcrtc_rooms_db import list_rooms, pool_metrics

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(delete(OlcrtcRoomSticky).where(
            OlcrtcRoomSticky.fingerprint.like("lt1000-%")
            | OlcrtcRoomSticky.fingerprint.like("prove-%")
            | OlcrtcRoomSticky.fingerprint.like("load-%")
            | OlcrtcRoomSticky.fingerprint.like("lte-%")
            | OlcrtcRoomSticky.fingerprint.like("scale-%")
        ))
        for r in await list_rooms(db):
            r.online_count = 0
            if r.provider in ("telemost", "wbstream") and int(r.max_clients or 0) < 25:
                r.max_clients = 25
        await db.commit()
        m = await pool_metrics(db)
        print("METRICS", json.dumps(m, ensure_ascii=False))

    for dt in ("pc", "android"):
        d = json.load(urllib.request.urlopen(
            f"http://127.0.0.1:8000/api/vpn/olcrtc-config?device_type={dt}&fingerprint=lte-ok-{dt}",
            timeout=15,
        ))
        p = d.get("providers") or {}
        print("CFG", dt, json.dumps({
            "pool_denied": d.get("pool_denied"),
            "telemost_enabled": p.get("telemost", {}).get("enabled"),
            "telemost_room": p.get("telemost", {}).get("room"),
            "wb_enabled": p.get("wbstream", {}).get("enabled"),
            "wb_room": p.get("wbstream", {}).get("room"),
            "jitsi": (p.get("jitsi") or {}).get("room", "")[:60],
        }, ensure_ascii=False))

asyncio.run(main())
"""

def main():
    c = connect()
    sftp = c.open_sftp()
    sftp.putfo(io.BytesIO(REMOTE.encode()), "/tmp/fix_olcrtc_load.py")
    run(c, "docker cp /tmp/fix_olcrtc_load.py backend-api-1:/tmp/fix_olcrtc_load.py")
    print(run(c, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/fix_olcrtc_load.py"))
    sftp.close(); c.close()

if __name__ == "__main__":
    main()
