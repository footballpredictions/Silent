"""Force re-apply / tear dead android units; recreate warm stock."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = b"""
import asyncio, sys
sys.path.insert(0, "/app")

async def main():
    from sqlalchemy import delete, select
    from app.database import AsyncSessionLocal
    from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
    from app.services.olcrtc2_assign import ensure_warm_pool
    from app.services.olcrtc2_cell_units import apply_olcrtc2_unit, teardown_olcrtc2_unit

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Olcrtc2Sticky))
        await db.commit()
        rooms = (await db.execute(select(Olcrtc2Room))).scalars().all()
        print("rooms", len(rooms))
        for r in rooms:
            url = (r.room_url or "")
            bad = any(x in url for x in ("590478", "539767", "251431"))
            print("unit", r.unit_name, url[-24:], r.status, "force_tear" if bad else "reapply")
            if bad or r.device_type == "android":
                await teardown_olcrtc2_unit(db, r)
                await db.delete(r)
                await db.commit()
            else:
                applied = await apply_olcrtc2_unit(db, r)
                print("  apply", applied.get("ok"), applied.get("message"))
        stats = await ensure_warm_pool(db)
        print("warm", stats)
        left = (await db.execute(select(Olcrtc2Room))).scalars().all()
        for r in left:
            print("ok", r.device_type, r.unit_name, (r.room_url or "")[-24:], r.status)

asyncio.run(main())
"""


def main() -> None:
    c = connect()
    try:
        sftp = c.open_sftp()
        sftp.putfo(io.BytesIO(INNER), "/tmp/heal_olcrtc2_inner.py")
        sftp.close()
        run(c, "docker cp /tmp/heal_olcrtc2_inner.py backend-api-1:/tmp/heal_olcrtc2_inner.py")
        run(
            c,
            "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/heal_olcrtc2_inner.py",
            timeout=600,
        )
    finally:
        c.close()


if __name__ == "__main__":
    main()
