"""Heal olcrtc2 pool: tear dead/orphan rooms, re-warm Telemost+WB, verify units."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r'''
import asyncio, json, sys
from collections import defaultdict
from sqlalchemy import delete, func, select
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_assign import ensure_warm_pool, pool_stats, release_session_room
from app.services.olcrtc2_cell_units import apply_olcrtc2_unit, probe_olcrtc2_unit, teardown_olcrtc2_unit
from app.services.olcrtc2_settings import enabled_providers, load_olcrtc2_settings

async def snapshot(db):
    settings = await load_olcrtc2_settings(db)
    rooms = (await db.execute(select(Olcrtc2Room))).scalars().all()
    by = defaultdict(lambda: {"total":0,"active":0,"free":0,"online":0,"prov":0,"err":0,"units":[]})
    for r in rooms:
        k=f"{r.provider}:{r.device_type}"
        by[k]["total"]+=1
        st=int((await db.execute(select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id==r.id))).scalar() or 0)
        by[k]["online"]+=st
        if r.status=="active":
            by[k]["active"]+=1
            if st==0: by[k]["free"]+=1
        elif r.status=="provisioning": by[k]["prov"]+=1
        elif r.status=="error": by[k]["err"]+=1
        probe = await probe_olcrtc2_unit(db, r) if r.unit_name else {"active": False, "message":"no unit"}
        by[k]["units"].append({
            "unit": r.unit_name, "status": r.status, "room": (r.room_url or "")[:40],
            "stickies": st, "tok": (r.auth_token or "").startswith("eyJ"),
            "probe": probe.get("state") or probe.get("message") or ("active" if probe.get("active") else "dead"),
            "probe_active": bool(probe.get("active") or probe.get("unknown")),
        })
    return {
        "settings": {
            "enabled": settings.get("enabled"),
            "agent": settings.get("agent_enabled"),
            "warm": int(settings.get("warm_pool_per_dt") or 0),
            "providers": enabled_providers(settings),
            "cells": settings.get("cells"),
        },
        "pool_stats": await pool_stats(db),
        "by_key": {k: {kk:vv for kk,vv in v.items() if kk!="units"} for k,v in by.items()},
        "units": {k: v["units"] for k,v in by.items()},
    }

async def main():
    do_heal = sys.argv[1] != "0"
    async with AsyncSessionLocal() as db:
        before = await snapshot(db)
        print("BEFORE", json.dumps(before, ensure_ascii=False, default=str))
        torn=0
        reapplied=0
        if do_heal:
            rooms = (await db.execute(select(Olcrtc2Room))).scalars().all()
            for r in list(rooms):
                probe = await probe_olcrtc2_unit(db, r)
                dead = not (probe.get("active") or probe.get("unknown"))
                # WB without JWT cannot host
                wb_bad = (r.provider=="wbstream") and not (r.auth_token or "").startswith("eyJ")
                # sticky loadtest leftovers
                if dead or wb_bad or r.status in ("error","provisioning"):
                    await db.execute(delete(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id==r.id))
                    await teardown_olcrtc2_unit(db, r)
                    if (r.provider or "") == "wbstream":
                        try:
                            from ai.olcrtc_wb_api import delete_wbstream_room_api
                            tok=(r.auth_token or "").strip()
                            if tok.startswith("eyJ") and r.room_url:
                                await delete_wbstream_room_api(tok, r.room_url)
                        except Exception:
                            pass
                    await db.delete(r)
                    await db.commit()
                    torn += 1
                    continue
                # live but ensure MODE/token applied (esp WB)
                if (r.provider=="wbstream") and r.status=="active":
                    applied = await apply_olcrtc2_unit(db, r)
                    if applied.get("ok"):
                        reapplied += 1
            print("HEAL", json.dumps({"torn": torn, "reapplied": reapplied}))
            warm = await ensure_warm_pool(db)
            print("WARM", json.dumps(warm, ensure_ascii=False, default=str))
        after = await snapshot(db)
        print("AFTER", json.dumps(after, ensure_ascii=False, default=str))

asyncio.run(main())
'''


def main() -> None:
    heal = "1" if (len(sys.argv) < 2 or sys.argv[1] != "--check") else "0"
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode()), "/tmp/heal_olcrtc2_now.py")
    sftp.close()
    run(queen, "docker cp /tmp/heal_olcrtc2_now.py backend-api-1:/tmp/heal_olcrtc2_now.py")
    raw = run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/heal_olcrtc2_now.py {heal}",
        timeout=900,
    )
    print(raw)
    queen.close()


if __name__ == "__main__":
    main()
