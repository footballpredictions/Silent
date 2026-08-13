"""Re-apply all wbstream olcrtc2 units (after cell-agent MODE fix)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r"""
import asyncio, sys
sys.path.insert(0, "/app")

async def main():
    from sqlalchemy import delete, select
    from app.database import AsyncSessionLocal
    from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
    from app.services.olcrtc2_assign import ensure_warm_pool, _remote_delete_room
    from app.services.olcrtc2_cell_units import apply_olcrtc2_unit, teardown_olcrtc2_unit

    async with AsyncSessionLocal() as db:
        rooms = (await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.provider == "wbstream"))).scalars().all()
        print("wb_rooms", len(rooms))
        for r in list(rooms):
            print("tear", r.unit_name, r.room_url[-20:], r.status)
            await db.execute(delete(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id))
            await teardown_olcrtc2_unit(db, r)
            await _remote_delete_room(r)
            await db.delete(r)
            await db.commit()
        stats = await ensure_warm_pool(db)
        print("warm", stats)
        left = (await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.provider == "wbstream"))).scalars().all()
        for r in left:
            # force re-apply to rewrite env with MODE=wbstream
            applied = await apply_olcrtc2_unit(db, r)
            print("apply", r.unit_name, applied.get("ok"), str(applied.get("message") or "")[:100])
            if applied.get("ok"):
                r.status = "active"
                await db.commit()

asyncio.run(main())
""".encode("utf-8")


def main() -> None:
    c = connect()
    try:
        sftp = c.open_sftp()
        sftp.putfo(io.BytesIO(INNER), "/tmp/reapply_wb.py")
        sftp.close()
        run(c, "docker cp /tmp/reapply_wb.py backend-api-1:/tmp/reapply_wb.py")
        run(
            c,
            "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/reapply_wb.py",
            timeout=600,
        )
    finally:
        c.close()


if __name__ == "__main__":
    main()
