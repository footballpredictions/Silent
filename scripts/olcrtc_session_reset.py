"""Прод wipe olcrtc → session-mode (как VK): снести пул, sticky, unit'ы; Telemost-only.

  cd backend
  python scripts/olcrtc_session_reset.py

Шаги:
1) stop host-provision (на время wipe)
2) disable --now все olcrtc@*
3) БД: truncate sticky + rooms; settings placeholders; telemost-only
4) agent state: session_mode=true, max_clients=1, min_free=0, enabled=false (включите после деплоя)
5) снести server-*.yaml / data-* на хосте (бинарь и шаблоны оставить)
6) start host-provision с OLCRTC_HOST_CREATE_PARALLEL=1
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import connect, run  # noqa: E402

REMOTE_OLCRTC = "/opt/silent-vpn/olcrtc"


def main() -> None:
    client = connect()
    sftp = client.open_sftp()

    print("=== stop host-provision (safe during wipe) ===")
    run(client, "systemctl stop silent-olcrtc-host-provision 2>/dev/null || true")

    print("=== stop/disable all olcrtc@* units ===")
    run(
        client,
        "systemctl list-units 'olcrtc@*' --all --no-legend 2>/dev/null "
        "| awk '{print $1}' | while read u; do "
        "systemctl disable --now \"$u\" 2>/dev/null || true; done; "
        "systemctl list-units 'olcrtc@*' --all --no-legend 2>/dev/null | head -20 || true",
    )

    py = r"""
import asyncio
import json
from sqlalchemy import delete, select, text
from app.database import AsyncSessionLocal
from app.models import AppSetting
from app.models.olcrtc_room import OlcrtcRoom, OlcrtcRoomSticky
from app.services.olcrtc_settings import (
    load_olcrtc_settings,
    save_olcrtc_settings,
    is_placeholder_room,
)
from app.services.olcrtc_rooms_db import pool_metrics

AGENT_KEY = "olcrtc_room_agent"

async def main():
    async with AsyncSessionLocal() as db:
        sticky = await db.execute(delete(OlcrtcRoomSticky))
        print("sticky deleted", sticky.rowcount)
        rooms = await db.execute(delete(OlcrtcRoom))
        print("rooms deleted", rooms.rowcount)
        await db.commit()

        settings = await load_olcrtc_settings(db)
        for name, pcfg in list(settings.providers.items()):
            if name in ("telemost", "wbstream"):
                pcfg.enabled = True
                rooms_slots = list(pcfg.rooms or [])
                for slot in rooms_slots:
                    slot.url = "PLACEHOLDER"
                    slot.max_clients = 1
                if not rooms_slots:
                    from app.services.olcrtc_settings import OlcrtcRoomSlot
                    rooms_slots = [
                        OlcrtcRoomSlot(id="pc", url="PLACEHOLDER", max_clients=1),
                        OlcrtcRoomSlot(id="android", url="PLACEHOLDER", max_clients=1),
                    ]
                pcfg.rooms = rooms_slots
            else:
                pcfg.enabled = False
                for slot in list(pcfg.rooms or []):
                    slot.url = "PLACEHOLDER"
                    slot.max_clients = 1
            settings.providers[name] = pcfg
        await save_olcrtc_settings(db, settings)
        print("settings: telemost-only, placeholders")

        agent = {
            "enabled": False,
            "session_mode": True,
            "bootstrap_warm": 0,
            "auto_apply_yaml": True,
            "auto_units": True,
            "max_clients": 1,
            "min_free_per_slot": 0,
            "min_rooms_per_slot": 0,
            "max_rooms_per_slot": 64,
            "idle_room_ttl_min": 5,
            "liveness_prune": True,
            "target_capacity": 0,
            "target_free_ratio": 0.0,
            "target_rooms_telemost": 0,
            "target_rooms_wbstream": 0,
            "run_log": ["session reset wipe"],
            "last_error": "",
            "last_ok": "",
            "last_run_at": "",
            "cooldown_until": "",
            "last_liveness": {},
            "idle_since": {},
            "last_scale": {"mode": "session", "at": "reset"},
        }
        result = await db.execute(select(AppSetting).where(AppSetting.key == AGENT_KEY))
        row = result.scalar_one_or_none()
        payload = json.dumps(agent, ensure_ascii=False)
        if row:
            row.value = payload
        else:
            db.add(AppSetting(key=AGENT_KEY, value=payload))
        await db.commit()
        print("agent state: session_mode=true enabled=false max_clients=1")
        print("metrics", await pool_metrics(db))

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/olcrtc_session_reset_inner.py")
    run(client, "docker cp /tmp/olcrtc_session_reset_inner.py backend-api-1:/tmp/olcrtc_session_reset_inner.py")
    print("=== DB wipe inside api container ===")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 "
            "python /tmp/olcrtc_session_reset_inner.py",
        )
    )

    print("=== clean host yaml/data (keep binary + templates) ===")
    run(
        client,
        f"cd {REMOTE_OLCRTC} && "
        f"rm -f server-*.yaml 2>/dev/null; "
        f"rm -rf data-* 2>/dev/null; "
        f"ls -la {REMOTE_OLCRTC} | head -40",
    )

    print("=== start host-provision (Semaphore/parallel=1) ===")
    run(
        client,
        "systemctl reset-failed silent-olcrtc-host-provision 2>/dev/null || true; "
        "systemctl start silent-olcrtc-host-provision; "
        "sleep 2; "
        "systemctl is-active silent-olcrtc-host-provision; "
        "curl -sS -m 3 http://127.0.0.1:9101/v1/status || true",
    )

    print(
        "wipe done — next: deploy_stable (session-mode code), "
        "enable agent in admin, smoke Telemost connect/disconnect"
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
