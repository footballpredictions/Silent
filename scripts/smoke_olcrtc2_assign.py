"""Verify specific WB room + smoke assign for android telemost/wbstream."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

INNER = r'''
import asyncio, json, sys, time, httpx
from sqlalchemy import select, func
from app.database import AsyncSessionLocal
from app.models.olcrtc2_room import Olcrtc2Room, Olcrtc2Sticky
from app.services.olcrtc2_assign import assign_public_config, ensure_session_room
from app.services.olcrtc2_cell_units import probe_olcrtc2_unit, apply_olcrtc2_unit
from app.services.olcrtc2_settings import room_to_public_config, load_olcrtc2_settings

WANT = sys.argv[1] if len(sys.argv)>1 else "svpn_20373c7e8225"

async def main():
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Olcrtc2Room).where(Olcrtc2Room.room_url.like(f"%{WANT}%")))).scalars().all()
        print("ROOM_LOOKUP", json.dumps([{
            "unit": r.unit_name, "status": r.status, "provider": r.provider,
            "room": r.room_url, "tok": (r.auth_token or "")[:12],
            "stickies": int((await db.execute(select(func.count()).select_from(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id==r.id))).scalar() or 0),
        } for r in rows], ensure_ascii=False))

        # smoke assign both providers
        out={}
        for prov in ("telemost","wbstream"):
            fp=f"smoke-fix-{prov}-{int(time.time())%100000}"
            t0=time.perf_counter()
            cfg = await assign_public_config(db, device_type="android", fingerprint=fp, preferred_provider=prov)
            ms=round((time.perf_counter()-t0)*1000)
            entry=(cfg.get("providers") or {}).get(prov) or {}
            room=entry.get("room") or ""
            unit=cfg.get("assigned_slot") or entry.get("room_slot_id")
            rid=entry.get("room_db_id") or ""
            tok=bool(entry.get("auth_token"))
            denied=bool(cfg.get("pool_denied"))
            probe=None
            if rid and not denied:
                from uuid import UUID
                row=await db.get(Olcrtc2Room, UUID(rid))
                if row:
                    probe=await probe_olcrtc2_unit(db, row)
                    # force re-apply WB to ensure host JWT in env
                    if prov=="wbstream":
                        applied=await apply_olcrtc2_unit(db, row)
                        probe={"probe": probe, "reapply": applied}
            out[prov]={
                "ms": ms, "denied": denied, "detail": cfg.get("pool_denied_detail"),
                "room": room, "unit": unit, "auth_token": tok,
                "enabled": cfg.get("enabled"), "probe": probe,
            }
        print("SMOKE_ASSIGN", json.dumps(out, ensure_ascii=False, default=str))

        # HTTP path like client
        async with httpx.AsyncClient(timeout=60) as client:
            for prov in ("telemost","wbstream"):
                fp=f"http-smoke-{prov}-{int(time.time())%100000}"
                r=await client.get(
                    f"http://127.0.0.1:8000/api/vpn/olcrtc2-config?device_type=android&fingerprint={fp}&provider={prov}"
                )
                body=r.json() if r.content else {}
                entry=(body.get("providers") or {}).get(prov) or {}
                print("HTTP", prov, json.dumps({
                    "status": r.status_code,
                    "denied": body.get("pool_denied"),
                    "detail": body.get("pool_denied_detail"),
                    "room": entry.get("room"),
                    "has_auth": bool(entry.get("auth_token")),
                    "slot": body.get("assigned_slot"),
                }, ensure_ascii=False))

asyncio.run(main())
'''


def main() -> None:
    room = sys.argv[1] if len(sys.argv) > 1 else "svpn_20373c7e8225"
    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(INNER.encode()), "/tmp/smoke_assign.py")
    sftp.close()
    run(queen, "docker cp /tmp/smoke_assign.py backend-api-1:/tmp/smoke_assign.py")
    print(run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/smoke_assign.py {room}",
        timeout=180,
    ))
    queen.close()


if __name__ == "__main__":
    main()
