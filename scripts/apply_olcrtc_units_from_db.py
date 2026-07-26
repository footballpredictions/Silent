"""Пересобрать server-*.yaml из OlcrtcRoom (БД) и поднять unit'ы на Улье.

  cd backend
  python scripts/apply_olcrtc_units_from_db.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from _deploy_common import BACKEND_ROOT, REMOTE, connect, run  # noqa: E402

REMOTE_OLCRTC = "/opt/silent-vpn/olcrtc"

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


def main() -> None:
    client = connect()
    sftp = client.open_sftp()

    for rel in API_FILES:
        lp = BACKEND_ROOT / rel.replace("/", "\\")
        if not lp.is_file():
            continue
        rp = f"{REMOTE}/{rel}"
        run(client, f"mkdir -p {Path(rp).parent.as_posix()}")
        sftp.put(str(lp), rp)
        run(client, f"docker cp {rp} backend-api-1:/app/{rel}")
        print("cp", rel)

    gen_py = r"""
import asyncio
from app.database import AsyncSessionLocal
from app.services.olcrtc_rooms_db import (
    sync_rooms_from_settings_json,
    write_all_unit_yaml_from_db,
    pool_metrics,
    list_rooms,
)

async def main():
    async with AsyncSessionLocal() as db:
        n = await sync_rooms_from_settings_json(db)
        print("synced", n)
        files = await write_all_unit_yaml_from_db(db)
        print("units", ",".join(sorted(files.keys())))
        m = await pool_metrics(db)
        print("metrics", m)
        rooms = await list_rooms(db)
        for r in rooms:
            print("room", r.unit_name, r.provider, r.status, r.room_url[:40], "online", r.online_count, "/", r.max_clients)

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(gen_py.encode()), "/tmp/gen_olcrtc_db.py")
    run(client, "docker cp /tmp/gen_olcrtc_db.py backend-api-1:/tmp/gen_olcrtc_db.py")
    # restart api so models create_all
    run(client, "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api >/dev/null")
    run(client, "sleep 14")
    print(run(client, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/gen_olcrtc_db.py"))

    run(
        client,
        f"mkdir -p {REMOTE_OLCRTC}/data "
        f"{REMOTE_OLCRTC}/data-pc-telemost {REMOTE_OLCRTC}/data-pc-wbstream "
        f"{REMOTE_OLCRTC}/data-android-telemost {REMOTE_OLCRTC}/data-android-wbstream",
    )
    # Jitsi units off
    run(
        client,
        "systemctl list-units 'olcrtc@*-jitsi*' --all --no-legend 2>/dev/null "
        "| awk '{print $1}' | while read u; do systemctl disable --now \"$u\" 2>/dev/null || true; done",
    )
    sync = f"""#!/bin/bash
set -e
# не тащить legacy *-jitsi*
rm -f {REMOTE_OLCRTC}/server-*-jitsi.yaml {REMOTE_OLCRTC}/server-*-jitsi-*.yaml 2>/dev/null || true
docker exec backend-api-1 sh -c 'rm -f /app/update/olcrtc/server-*-jitsi*.yaml 2>/dev/null || true'
for y in $(docker exec backend-api-1 sh -c 'ls /app/update/olcrtc/server*.yaml 2>/dev/null' || true); do
  bn=$(basename "$y")
  case "$bn" in
    *jitsi*) echo "skip $bn"; continue ;;
  esac
  docker cp "backend-api-1:$y" "{REMOTE_OLCRTC}/$bn"
  echo "sync $bn"
done
chmod 600 {REMOTE_OLCRTC}/server*.yaml 2>/dev/null || true
"""
    sftp.putfo(io.BytesIO(sync.encode()), "/tmp/sync_olcrtc_yaml.sh")
    run(client, "bash /tmp/sync_olcrtc_yaml.sh")

    for legacy in ("pc", "android"):
        run(client, f"systemctl disable --now olcrtc@{legacy}.service 2>/dev/null || true")

    listing = run(client, f"ls {REMOTE_OLCRTC}/server-*.yaml 2>/dev/null || true")
    slots = []
    for line in listing.splitlines():
        name = Path(line.strip()).name
        if name.startswith("server-") and name.endswith(".yaml"):
            slot = name[len("server-") : -len(".yaml")]
            if slot in ("pc", "android") or slot.endswith("-jitsi") or "-jitsi-" in slot:
                continue
            slots.append(slot)

    run(client, "systemctl daemon-reload")
    unique_slots = sorted(set(slots))
    # mkdir batch
    mkdir_cmd = " ".join(f"{REMOTE_OLCRTC}/data-{s}" for s in unique_slots)
    if mkdir_cmd:
        run(client, f"mkdir -p {mkdir_cmd}")
    # enable+restart пачками (масса unit'ов — иначе SSH EOF)
    batch: list[str] = []
    for slot in unique_slots:
        batch.append(slot)
        if len(batch) >= 8:
            units = " ".join(f"olcrtc@{s}.service" for s in batch)
            run(client, f"systemctl enable {units}")
            run(client, f"systemctl restart {units}", timeout=180)
            batch = []
    if batch:
        units = " ".join(f"olcrtc@{s}.service" for s in batch)
        run(client, f"systemctl enable {units}")
        run(client, f"systemctl restart {units}", timeout=180)
    run(
        client,
        "systemctl list-units 'olcrtc@*' --no-pager --plain | awk '{print $1,$3,$4}' | head -60",
    )

    run(
        client,
        'curl -s "http://127.0.0.1:8000/api/vpn/olcrtc-config?device_type=pc&fingerprint=scale-test" | head -c 500; echo',
    )
    sftp.close()
    client.close()
    print("Done — queen units from OlcrtcRoom DB")


if __name__ == "__main__":
    main()
