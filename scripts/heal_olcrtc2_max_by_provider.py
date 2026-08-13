"""Set Telemost max_clients=3, WB=25 (vp8 vs wide channel)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r'''
import asyncio, json
from sqlalchemy import text, select
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE olcrtc2_rooms SET max_clients = 3 WHERE provider = 'telemost'"
        ))
        await db.execute(text(
            "UPDATE olcrtc2_rooms SET max_clients = 25 WHERE provider = 'wbstream' AND COALESCE(max_clients,0) < 25"
        ))
        await db.commit()
        rows = (await db.execute(select(Olcrtc2Room))).scalars().all()
        by = {}
        for x in rows:
            k = f"{x.provider}/{x.device_type}/{x.status}"
            by.setdefault(k, {"n": 0, "min": 99, "max": 0})
            by[k]["n"] += 1
            by[k]["min"] = min(by[k]["min"], int(x.max_clients or 0))
            by[k]["max"] = max(by[k]["max"], int(x.max_clients or 0))
        print(json.dumps({"rooms": by}, ensure_ascii=False))

asyncio.run(main())
'''


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), "/tmp/heal_mc_prov.py")
    sftp.close()
    run(client, "docker cp /tmp/heal_mc_prov.py backend-api-1:/tmp/heal_mc_prov.py")
    run(
        client,
        "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/heal_mc_prov.py",
    )
    client.close()


if __name__ == "__main__":
    main()
