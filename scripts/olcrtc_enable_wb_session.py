"""Включить WB Stream в session-mode на проде + смоук create/leave.

  cd backend
  python scripts/olcrtc_enable_wb_session.py
"""
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

    # sync assign + settings (placeholder fix already on server ideally)
    for rel in (
        "app/services/olcrtc_assign.py",
        "app/services/olcrtc_settings.py",
        "app/services/olcrtc_rooms_db.py",
        "ai/olcrtc_room_agent.py",
        "ai/olcrtc_host_provision_client.py",
        "ai/olcrtc_wb_api.py",
    ):
        local = ROOT / rel
        if local.is_file():
            remote = f"/tmp/{local.name}"
            sftp.put(str(local), remote)
            dest = f"/app/{rel}"
            run(client, f"docker cp {remote} backend-api-1:{dest}")

    py = """
import asyncio
from app.database import AsyncSessionLocal
from app.services.olcrtc_settings import load_olcrtc_settings, save_olcrtc_settings
from app.services.olcrtc_room_accounts import (
    load_room_accounts,
    resolve_storage_state,
    sync_wbstream_auth_token_to_settings,
)
from app.services.olcrtc_rooms_db import list_rooms, pool_metrics
from app.services.olcrtc_assign import assign_public_config, release_session_room
from ai.olcrtc_room_agent import load_agent_state, save_agent_state
from ai.olcrtc_host_provision_client import host_provision_status, push_storage_to_host

async def main():
    async with AsyncSessionLocal() as db:
        st = await load_agent_state(db)
        st.session_mode = True
        st.enabled = True
        st.max_clients = 1
        st.min_free_per_slot = 0
        st.min_rooms_per_slot = 0
        st.cooldown_until = ""  # снять WB antibot cooldown если был
        await save_agent_state(db, st)

        settings = await load_olcrtc_settings(db)
        for name in ("telemost", "wbstream"):
            p = settings.providers.get(name)
            if not p:
                continue
            p.enabled = True
            for slot in list(p.rooms or []):
                slot.max_clients = 1
            settings.providers[name] = p
        await save_olcrtc_settings(db, settings)

        accounts = await load_room_accounts(db)
        host = await host_provision_status()
        print("host", host.get("reachable"), "wb_state", host.get("wbstream_state"))
        for acc in accounts.wbstream:
            storage = resolve_storage_state(acc)
            if storage:
                ok = await push_storage_to_host("wbstream", storage)
                print("push wb storage", ok, "keys", len(storage))
                break
        tok = await sync_wbstream_auth_token_to_settings(db)
        print("wb auth_token len", len(tok or ""))

        settings = await load_olcrtc_settings(db)
        print(
            "providers enabled",
            {n: p.enabled for n, p in settings.providers.items()},
        )

    # smoke WB pc
    async with AsyncSessionLocal() as db:
        print("=== smoke wbstream pc ===")
        cfg = await assign_public_config(
            db,
            device_type="pc",
            fingerprint="smoke-wb-pc-1",
            preferred_provider="wbstream",
        )
        p = (cfg.get("providers") or {}).get("wbstream") or {}
        print(
            "assign denied=", p.get("denied"),
            "room=", p.get("room"),
            "unit=", cfg.get("assigned_slot"),
            "db=", p.get("room_db_id"),
            "enabled=", p.get("enabled"),
        )
        rid = p.get("room_db_id") or ""
        if not rid or p.get("denied"):
            print("SMOKE FAIL wb pc")
            print("pool_denied", cfg.get("pool_denied"), cfg.get("pool_denied_detail"))
            return
        rel = await release_session_room(
            db,
            room_db_id=rid,
            fingerprint="smoke-wb-pc-1",
            provider="wbstream",
            reason="smoke leave",
        )
        print("release", rel)
        print("SMOKE OK wb pc")

    async with AsyncSessionLocal() as db:
        print("=== smoke wbstream android ===")
        cfg = await assign_public_config(
            db,
            device_type="android",
            fingerprint="smoke-wb-android-1",
            preferred_provider="wbstream",
        )
        p = (cfg.get("providers") or {}).get("wbstream") or {}
        print(
            "assign denied=", p.get("denied"),
            "room=", p.get("room"),
            "unit=", cfg.get("assigned_slot"),
            "db=", p.get("room_db_id"),
        )
        rid = p.get("room_db_id") or ""
        if not rid or p.get("denied"):
            print("SMOKE FAIL wb android")
            return
        rel = await release_session_room(
            db,
            room_db_id=rid,
            fingerprint="smoke-wb-android-1",
            provider="wbstream",
            reason="smoke leave",
        )
        print("release", rel)
        print("SMOKE OK wb android")
        print("metrics", await pool_metrics(db))
        print("rooms", [(r.unit_name, r.provider, r.online_count, r.room_url[:28]) for r in await list_rooms(db)])

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/olcrtc_enable_wb.py")
    run(client, "docker cp /tmp/olcrtc_enable_wb.py backend-api-1:/tmp/olcrtc_enable_wb.py")
    run(
        client,
        "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api",
    )
    time.sleep(12)
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/olcrtc_enable_wb.py",
        )
    )
    print(
        run(
            client,
            "systemctl list-units 'olcrtc@*' --no-legend 2>/dev/null | head -25 || true",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
