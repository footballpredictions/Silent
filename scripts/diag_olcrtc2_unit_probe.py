"""Probe olcrtc2 unit via cell-agent (no SSH)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r"""
import asyncio, json
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room
from app.services.olcrtc2_cell_units import probe_olcrtc2_unit, apply_olcrtc2_unit
from sqlalchemy import select

ROOM = "94038621041836"

async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Olcrtc2Room))).scalars().all()
        hit = [r for r in rows if ROOM in (r.room_url or "")]
        if not hit:
            print("NO_ROOM")
            return
        r = hit[0]
        print("unit", r.unit_name, "prov", r.provider, "status", r.status)
        print("key_prefix", (r.crypto_key or "")[:16])
        st = await probe_olcrtc2_unit(db, r)
        print("status_probe", json.dumps(st, ensure_ascii=False, default=str)[:800])
        # also list stickies for this room
        from app.models.olcrtc2_room import Olcrtc2Sticky
        stks = (await db.execute(select(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id))).scalars().all()
        print("stickies", len(stks))
        for s in stks:
            print(" sticky", s.fingerprint[:16], "upd", s.updated_at)

asyncio.run(main())
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), "/tmp/tm_probe.py")
    sftp.close()
    run(client, "docker cp /tmp/tm_probe.py backend-api-1:/tmp/tm_probe.py")
    run(client, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/tm_probe.py")
    client.close()


if __name__ == "__main__":
    main()
