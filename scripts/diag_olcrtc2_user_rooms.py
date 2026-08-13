"""Diagnose android olcrtc2 rooms (carrier/unit/sticky)."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r'''
import asyncio, json
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_assign import _carrier_room_alive
from app.services.olcrtc2_cell_units import probe_olcrtc2_unit

async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Olcrtc2Room).where(Olcrtc2Room.device_type == "android", Olcrtc2Room.status == "active")
        )).scalars().all()
        out = []
        for r in rows:
            unit = await probe_olcrtc2_unit(db, r)
            car = await _carrier_room_alive(r)
            n = int((await db.execute(
                select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id)
            )).scalar() or 0)
            out.append({
                "prov": r.provider,
                "unit": r.unit_name,
                "room": (r.room_url or "")[:56],
                "online": r.online_count,
                "max": r.max_clients,
                "sticky": n,
                "unit_ok": bool(unit.get("active") or unit.get("ok") or unit.get("unknown")),
                "unit_raw": {k: unit.get(k) for k in ("active", "ok", "unknown", "message") if k in unit},
                "carrier": car,
                "key_len": len(r.crypto_key or ""),
            })
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))

asyncio.run(main())
'''


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), "/tmp/diag_rooms.py")
    sftp.close()
    run(client, "docker cp /tmp/diag_rooms.py backend-api-1:/tmp/diag_rooms.py")
    run(
        client,
        "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/diag_rooms.py",
    )
    client.close()


if __name__ == "__main__":
    main()
