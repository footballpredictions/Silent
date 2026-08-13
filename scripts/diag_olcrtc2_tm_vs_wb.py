"""Compare telemost vs wbstream pool load on prod."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r"""
import asyncio
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_settings import load_olcrtc2_settings, cell_ip_for_provider
from app.services.olcrtc2_cell_units import probe_olcrtc2_unit

async def main():
    async with AsyncSessionLocal() as db:
        s = await load_olcrtc2_settings(db)
        print("tm_cell", cell_ip_for_provider(s, "telemost"))
        print("wb_cell", cell_ip_for_provider(s, "wbstream"))
        for prov in ("telemost", "wbstream"):
            rows = (await db.execute(
                select(Olcrtc2Room).where(Olcrtc2Room.provider == prov, Olcrtc2Room.status == "active")
            )).scalars().all()
            stickies = (await db.execute(select(func.count()).select_from(Olcrtc2Sticky))).scalar() or 0
            print("---", prov, "active_rooms", len(rows))
            print(" max_clients", sorted({int(r.max_clients or 0) for r in rows}))
            print(" online_sum", sum(int(r.online_count or 0) for r in rows))
            andr = [r for r in rows if r.device_type == "android"]
            print(" android", len(andr))
            for r in andr[:4]:
                st = await probe_olcrtc2_unit(db, r)
                print(" ", r.unit_name, "room", (r.room_url or "")[:28],
                      "on", r.online_count, "max", r.max_clients,
                      "unit", st.get("active"), st.get("state"))

asyncio.run(main())
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), "/tmp/tm_vs_wb.py")
    sftp.close()
    run(client, "docker cp /tmp/tm_vs_wb.py backend-api-1:/tmp/tm_vs_wb.py")
    run(client, "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/tm_vs_wb.py")
    client.close()


if __name__ == "__main__":
    main()
