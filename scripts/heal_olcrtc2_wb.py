"""Tear broken olcrtc2 WB rooms (no JWT / wrong cell) and refill warm pool.

  cd backend
  python scripts/heal_olcrtc2_wb.py
"""
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
    from app.services.olcrtc2_assign import ensure_warm_pool
    from app.services.olcrtc2_cell_units import apply_olcrtc2_unit, teardown_olcrtc2_unit
    from app.services.olcrtc2_settings import save_olcrtc2_settings, load_olcrtc2_settings
    from app.services.olcrtc_room_accounts import (
        resolve_wbstream_access_token,
        sync_wbstream_auth_token_to_settings,
    )

    async with AsyncSessionLocal() as db:
        tok = await sync_wbstream_auth_token_to_settings(db) or ""
        if not tok:
            tok = await resolve_wbstream_access_token(db) or ""
        print("wb_jwt", "OK" if tok.startswith("eyJ") else "MISSING", "len", len(tok or ""))

        cur = await load_olcrtc2_settings(db)
        await save_olcrtc2_settings(db, {
            "providers_enabled": ["telemost", "wbstream"],
            "cells": {
                "telemost": (cur.get("cells") or {}).get("telemost") or "87.58.213.193",
                "wbstream": (cur.get("cells") or {}).get("wbstream") or "78.17.74.27",
            },
            "cell_ip": (cur.get("cells") or {}).get("telemost") or cur.get("cell_ip") or "87.58.213.193",
            "cell_ip_wbstream": (cur.get("cells") or {}).get("wbstream") or "78.17.74.27",
        })
        print("settings providers_enabled patched")

        rooms = (await db.execute(select(Olcrtc2Room))).scalars().all()
        print("rooms_before", len(rooms))
        for r in rooms:
            is_wb = (r.provider or "") == "wbstream"
            tok_ok = (r.auth_token or "").startswith("eyJ")
            print(
                "unit", r.unit_name, r.provider, r.device_type, r.status,
                "token" if tok_ok else "NO_TOKEN", (r.room_url or "")[-20:],
            )
            if is_wb:
                await db.execute(delete(Olcrtc2Sticky).where(Olcrtc2Sticky.room_id == r.id))
                await teardown_olcrtc2_unit(db, r)
                await db.delete(r)
                await db.commit()
                print("  torn wb")
            else:
                applied = await apply_olcrtc2_unit(db, r)
                print("  telemost reapply", applied.get("ok"), str(applied.get("message") or "")[:80])

        if not tok.startswith("eyJ"):
            print("SKIP warm wb: no JWT — add WB storage_state / cookies first")
        stats = await ensure_warm_pool(db)
        print("warm", stats)
        left = (await db.execute(select(Olcrtc2Room))).scalars().all()
        for r in left:
            print(
                "ok", r.provider, r.device_type, r.unit_name, r.status,
                "tok" if (r.auth_token or "").startswith("eyJ") else "-",
                (r.room_url or "")[-20:],
            )

asyncio.run(main())
""".encode("utf-8")


def main() -> None:
    c = connect()
    try:
        sftp = c.open_sftp()
        sftp.putfo(io.BytesIO(INNER), "/tmp/heal_olcrtc2_wb.py")
        sftp.close()
        run(c, "docker cp /tmp/heal_olcrtc2_wb.py backend-api-1:/tmp/heal_olcrtc2_wb.py")
        run(
            c,
            "docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/heal_olcrtc2_wb.py",
            timeout=600,
        )
    finally:
        c.close()


if __name__ == "__main__":
    main()
