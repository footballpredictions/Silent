"""Прогреть пул olcrtc под массу (~1000 online).

Создаёт Jitsi-комнаты в БД до capacity_total >= TARGET_CAPACITY,
включает room-agent, пишет YAML и поднимает unit'ы на Улье.

  cd backend
  python scripts/seed_olcrtc_mass_pool.py

Опционально:
  OLCRTC_TARGET_CAPACITY=1100
  OLCRTC_MAX_CLIENTS=25
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import BACKEND_ROOT, REMOTE, connect, run  # noqa: E402

TARGET_CAPACITY = int(os.environ.get("OLCRTC_TARGET_CAPACITY") or "1100")
MAX_CLIENTS = int(os.environ.get("OLCRTC_MAX_CLIENTS") or "25")

API_FILES = [
    "app/models/olcrtc_room.py",
    "app/models/__init__.py",
    "app/services/olcrtc_settings.py",
    "app/services/olcrtc_rooms_db.py",
    "app/services/olcrtc_assign.py",
    "app/services/olcrtc_cell_push.py",
    "app/services/olcrtc_room_accounts.py",
    "app/api/vpn.py",
    "app/api/admin.py",
    "app/main.py",
    "ai/olcrtc_room_agent.py",
    "ai/olcrtc_room_provision.py",
]


SEED_PY = f"""
import asyncio
import json
import secrets
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import AppSetting
from app.services.olcrtc_rooms_db import (
    create_room_row,
    list_rooms,
    pool_metrics,
    sync_rooms_from_settings_json,
    write_all_unit_yaml_from_db,
)
from app.services.olcrtc_settings import load_olcrtc_settings
from ai.olcrtc_room_agent import AGENT_KEY, AgentState, save_agent_state, heal_rooms

TARGET = {TARGET_CAPACITY}
MAX_C = {MAX_CLIENTS}
JITSI_PC = "https://meet.egovm.ru/SilentVpnOlcrtcHive"
JITSI_AN = "https://meet.playform.ru/SilentVpnOlcrtcHiveAndroid"

async def main():
    async with AsyncSessionLocal() as db:
        await sync_rooms_from_settings_json(db)
        settings = await load_olcrtc_settings(db)
        j = settings.providers.get("jitsi")
        if not j or not j.enabled:
            raise SystemExit("jitsi provider disabled — enable in admin first")

        metrics = await pool_metrics(db)
        print("before", metrics)

        # поднять max_clients у существующих jitsi active
        rooms = await list_rooms(db, provider="jitsi", status="active")
        bumped = 0
        for r in rooms:
            if int(r.max_clients or 0) < MAX_C:
                r.max_clients = MAX_C
                bumped += 1
        if bumped:
            await db.commit()
            print("bumped_max_clients", bumped)

        created = 0
        while True:
            metrics = await pool_metrics(db)
            cap = int(metrics.get("capacity_total") or 0)
            if cap >= TARGET:
                break
            rooms = await list_rooms(db, provider="jitsi", status="active")
            pc = sum(1 for r in rooms if r.slot_label == "pc" or "pc" in (r.device_types or []))
            an = sum(1 for r in rooms if r.slot_label == "android" or "android" in (r.device_types or []))
            slot = "pc" if pc <= an else "android"
            base = JITSI_AN if slot == "android" else JITSI_PC
            url = f"{{base}}-{{secrets.token_hex(3)}}"
            row = await create_room_row(
                db,
                provider="jitsi",
                room_url=url,
                slot_label=slot,
                device_types=[slot],
                max_clients=MAX_C,
                status="active",
            )
            created += 1
            print("created", row.unit_name, url, "cap_now", cap + MAX_C)
            if created > 200:
                raise SystemExit("safety stop >200 rooms")

        # включить агент на массу
        st = AgentState(
            enabled=True,
            auto_apply_yaml=True,
            target_capacity=TARGET,
            max_clients=MAX_C,
            target_free_ratio=0.10,
        )
        # сохранить поверх, сохранив лог если был
        result = await db.execute(select(AppSetting).where(AppSetting.key == AGENT_KEY))
        row = result.scalar_one_or_none()
        if row:
            try:
                prev = json.loads(row.value)
                st.run_log = list(prev.get("run_log") or [])[-20:]
            except Exception:
                pass
        await save_agent_state(db, st)
        print("agent enabled target_capacity", TARGET, "max_clients", MAX_C)

        files = await write_all_unit_yaml_from_db(db)
        metrics = await pool_metrics(db)
        print("after", metrics)
        print("units", len(files), ",".join(sorted(files.keys())[:12]), "...")

asyncio.run(main())
"""


def main() -> None:
    print(f"=== seed mass pool target_capacity={TARGET_CAPACITY} max_clients={MAX_CLIENTS} ===")
    client = connect()
    sftp = client.open_sftp()

    for rel in API_FILES:
        lp = BACKEND_ROOT / rel.replace("/", "\\")
        if not lp.is_file():
            print("skip missing", rel)
            continue
        rp = f"{REMOTE}/{rel}"
        run(client, f"mkdir -p {Path(rp).parent.as_posix()}")
        sftp.put(str(lp), rp)
        run(client, f"docker cp {rp} backend-api-1:/app/{rel}")
        print("cp", rel)

    sftp.putfo(io.BytesIO(SEED_PY.encode()), "/tmp/seed_olcrtc_mass.py")
    run(client, "docker cp /tmp/seed_olcrtc_mass.py backend-api-1:/tmp/seed_olcrtc_mass.py")
    run(client, "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api >/dev/null")
    run(client, "sleep 16")
    print(run(client, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/seed_olcrtc_mass.py"))

    sftp.close()
    client.close()

    # поднять все unit'ы из БД
    print("=== apply units ===")
    from apply_olcrtc_units_from_db import main as apply_main

    apply_main()
    print("=== DONE mass pool ===")


if __name__ == "__main__":
    main()
