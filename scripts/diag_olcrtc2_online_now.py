"""Live olcrtc2 stickies + Device.is_connected vs pool online."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r"""
import asyncio, json
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.device import Device
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_assign import pool_stats

async def main():
    async with AsyncSessionLocal() as db:
        online = (
            await db.execute(
                select(func.count()).select_from(Device).where(Device.is_connected == True)  # noqa: E712
            )
        ).scalar()
        stickies = (await db.execute(select(func.count()).select_from(Olcrtc2Sticky))).scalar()
        stats = await pool_stats(db)
        rows = []
        for s in (await db.execute(select(Olcrtc2Sticky))).scalars().all():
            room = await db.get(Olcrtc2Room, s.room_id)
            devs = (
                await db.execute(
                    select(Device).where(Device.device_fingerprint == s.fingerprint)
                )
            ).scalars().all()
            rows.append({
                "fp": (s.fingerprint or "")[:20],
                "prov": s.provider,
                "dt": s.device_type,
                "room": (room.room_url if room else "")[:28],
                "unit": room.unit_name if room else None,
                "room_online": room.online_count if room else None,
                "hb": str(s.updated_at),
                "devs": [
                    {
                        "name": d.device_name,
                        "conn": bool(d.is_connected),
                        "uid": str(d.user_id)[:8],
                    }
                    for d in devs
                ],
            })
        print(json.dumps({
            "device_online": online,
            "stickies": stickies,
            "pool": stats,
            "detail": rows,
        }, ensure_ascii=False, default=str))

asyncio.run(main())
"""


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode()), "/tmp/diag_on.py")
    sftp.close()
    run(queen, "docker cp /tmp/diag_on.py backend-api-1:/tmp/diag_on.py")
    run(queen, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/diag_on.py")
    queen.close()


if __name__ == "__main__":
    main()
