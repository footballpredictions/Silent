# -*- coding: utf-8 -*-
"""Smoke: probe a few warm WB/Telemost rooms via liveness."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r'''
import asyncio, json
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from ai.olcrtc_room_liveness import probe_room

async def main():
    async with AsyncSessionLocal() as db:
        out = {"wb": [], "tm": []}
        for prov, key in (("wbstream", "wb"), ("telemost", "tm")):
            rows = (await db.execute(
                select(Olcrtc2Room).where(
                    Olcrtc2Room.provider == prov,
                    Olcrtc2Room.device_type == "android",
                    Olcrtc2Room.status == "active",
                ).order_by(Olcrtc2Room.created_at.asc()).limit(5)
            )).scalars().all()
            for r in rows:
                st = int((await db.execute(
                    select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id)
                )).scalar() or 0)
                p = await probe_room(prov, r.room_url or "")
                out[key].append({
                    "unit": r.unit_name,
                    "room": (r.room_url or "")[:36],
                    "stickies": st,
                    "alive": p.alive,
                    "reason": (p.reason or "")[:80],
                    "http": p.http_status,
                })
        print(json.dumps(out, ensure_ascii=False))
asyncio.run(main())
'''


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode()), "/tmp/smoke_carrier.py")
    sftp.close()
    run(queen, "docker cp /tmp/smoke_carrier.py backend-api-1:/tmp/smoke_carrier.py")
    print(run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/smoke_carrier.py", timeout=180))
    queen.close()


if __name__ == "__main__":
    main()
