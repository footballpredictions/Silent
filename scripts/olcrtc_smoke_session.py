"""Smoke: assign Telemost session room + release teardown on prod (pc + android)."""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import connect, run  # noqa: E402


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    py = """
import asyncio
from app.database import AsyncSessionLocal
from app.services.olcrtc_rooms_db import list_rooms, pool_metrics
from app.services.olcrtc_assign import assign_public_config, release_session_room

async def smoke(device_type: str, fp: str):
    async with AsyncSessionLocal() as db:
        print("===", device_type, "===")
        rooms = await list_rooms(db)
        print("rooms_before", [
            (r.unit_name, r.room_url, r.status, r.slot_label, r.online_count)
            for r in rooms if r.status in ("active", "provisioning")
        ])
        cfg = await assign_public_config(
            db,
            device_type=device_type,
            fingerprint=fp,
            preferred_provider="telemost",
        )
        pref = cfg.get("preferred_provider")
        p = (cfg.get("providers") or {}).get(pref) or {}
        print(
            "assign session=", cfg.get("session_mode"),
            "denied=", p.get("denied"),
            "room=", p.get("room"),
            "unit=", cfg.get("assigned_slot"),
            "db=", p.get("room_db_id"),
        )
        rid = p.get("room_db_id") or ""
        if not rid or p.get("denied"):
            print("SMOKE FAIL", device_type)
            return False
        rel = await release_session_room(
            db,
            room_db_id=rid,
            fingerprint=fp,
            provider="telemost",
            reason="smoke leave",
        )
        print("release", rel)
        rooms2 = await list_rooms(db, status="active")
        still = [r for r in rooms2 if str(r.id) == rid]
        print("torn_gone", len(still) == 0, "active_left", len(rooms2))
        ok = bool(rel.get("torn_down", 0) >= 1 or len(still) == 0)
        print("SMOKE", "OK" if ok else "FAIL", device_type)
        return ok

async def main():
    async with AsyncSessionLocal() as db:
        print("metrics", await pool_metrics(db))
    ok_pc = await smoke("pc", "smoke-session-pc-2")
    ok_an = await smoke("android", "smoke-session-android-2")
    print("RESULT", "PASS" if (ok_pc and ok_an) else "FAIL", "pc=", ok_pc, "android=", ok_an)

asyncio.run(main())
"""
    # sync latest assign
    local = ROOT / "app" / "services" / "olcrtc_assign.py"
    sftp.put(str(local), "/tmp/olcrtc_assign.py")
    run(client, "docker cp /tmp/olcrtc_assign.py backend-api-1:/app/app/services/olcrtc_assign.py")
    run(
        client,
        "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api",
    )
    time.sleep(10)

    sftp.putfo(io.BytesIO(py.encode()), "/tmp/olcrtc_smoke_session.py")
    run(client, "docker cp /tmp/olcrtc_smoke_session.py backend-api-1:/tmp/olcrtc_smoke_session.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/olcrtc_smoke_session.py",
        )
    )
    print(
        run(
            client,
            "systemctl list-units 'olcrtc@*' --no-legend 2>/dev/null | head -20 || true",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
