"""Enable olcrtc2 + tear dead warm rooms + refill. Run from backend/: python scripts/heal_olcrtc2_pool_now.py"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r'''
import asyncio, json, secrets
from sqlalchemy import select, func, delete
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_settings import load_olcrtc2_settings, save_olcrtc2_settings
from app.services.olcrtc2_assign import (
    pool_stats, ensure_warm_pool, _carrier_room_alive, _tear_dead_room,
)
from app.services.olcrtc2_cell_units import probe_olcrtc2_unit

async def main():
    async with AsyncSessionLocal() as db:
        cur = await load_olcrtc2_settings(db)
        patch = {
            "enabled": True,
            "agent_enabled": True,
            "warm_pool_per_dt": int(cur.get("warm_pool_per_dt") or 3),
            "providers_enabled": cur.get("providers_enabled") or ["telemost", "wbstream"],
        }
        if not (cur.get("crypto_key") or "").strip():
            patch["crypto_key"] = secrets.token_hex(32)
        data = await save_olcrtc2_settings(db, patch)
        print("ENABLED", json.dumps({
            "enabled": data.get("enabled"),
            "agent": data.get("agent_enabled"),
            "warm": data.get("warm_pool_per_dt"),
            "providers": data.get("providers_enabled"),
            "key_len": len(data.get("crypto_key") or ""),
        }, ensure_ascii=False))

        rows = (await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.status == "active"))).scalars().all()
        torn = 0
        kept = 0
        for r in rows:
            unit = await probe_olcrtc2_unit(db, r)
            unit_ok = bool(unit.get("active") or unit.get("ok"))
            carrier = await _carrier_room_alive(r) if unit_ok else False
            if unit_ok and carrier is True:
                kept += 1
                continue
            # False or None — не отдаём клиенту мёртвое/сомнительное
            print("TEAR", r.provider, r.device_type, r.unit_name, (r.room_url or "")[:36],
                  "unit_ok", unit_ok, "carrier", carrier)
            await db.execute(delete(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id))
            await _tear_dead_room(db, r, reason="heal dead/unknown carrier")
            torn += 1
        print("HEAL torn", torn, "kept", kept)
        print("POOL_BEFORE_WARM", json.dumps(await pool_stats(db), ensure_ascii=False))
        warm = await ensure_warm_pool(db)
        print("WARM", json.dumps(warm, ensure_ascii=False, default=str))
        print("POOL_AFTER", json.dumps(await pool_stats(db), ensure_ascii=False))

asyncio.run(main())
'''


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode("utf-8")), "/tmp/heal_olcrtc2.py")
    sftp.close()
    run(client, "docker cp /tmp/heal_olcrtc2.py backend-api-1:/tmp/heal_olcrtc2.py")
    run(
        client,
        "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/heal_olcrtc2.py",
    )
    client.close()


if __name__ == "__main__":
    main()
