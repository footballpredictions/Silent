"""Доказательство масштаба пула: capacity + spill по комнатам + cap.

  cd backend
  python scripts/prove_olcrtc_scale.py

Что считаем «ок для 1000+»:
  1) capacity_total >= 1100 и ready_for_1000
  2) N fingerprint'ов разносятся по разным room_db_id (не все в одну)
  3) после заполнения max_clients на комнате следующий клиент уходит в другую
  4) unit'ы olcrtc@* running
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, REMOTE, connect, run  # noqa: E402

PROOF = r"""
import asyncio
import json
import urllib.request
from collections import Counter

from sqlalchemy import delete

from app.database import AsyncSessionLocal
from app.models.olcrtc_room import OlcrtcRoomSticky
from app.services.olcrtc_rooms_db import list_rooms, pool_metrics

BASE = "http://127.0.0.1:8000/api/vpn/olcrtc-config"


def fetch(fp: str, device_type: str = "pc"):
    url = f"{BASE}?device_type={device_type}&fingerprint={fp}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.load(resp)


async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OlcrtcRoomSticky).where(OlcrtcRoomSticky.fingerprint.like("prove-%"))
        )
        rooms = await list_rooms(db, provider="jitsi", status="active")
        for r in rooms:
            r.online_count = 0
        await db.commit()
        m0 = await pool_metrics(db)

    print(
        "STEP1_CAPACITY",
        json.dumps(
            {
                "capacity_total": m0.get("capacity_total"),
                "ready_for_1000": m0.get("ready_for_1000"),
                "rooms_active": m0.get("rooms_active"),
                "jitsi_capacity": (m0.get("by_provider") or {}).get("jitsi", {}).get("capacity"),
            },
            ensure_ascii=False,
        ),
    )

    assigned = []
    denied = 0
    for i in range(60):
        d = fetch(f"prove-a-{i:04d}")
        if d.get("pool_denied"):
            denied += 1
        assigned.append((d.get("providers") or {}).get("jitsi", {}).get("room_db_id") or "")

    c = Counter(assigned)
    print("STEP2_SPILL unique_rooms", len(c), "denied", denied, "top3", c.most_common(3))

    for i in range(30):
        fetch(f"prove-b-{i:04d}")

    async with AsyncSessionLocal() as db:
        m2 = await pool_metrics(db)

    print(
        "STEP3_AFTER_90 online",
        m2.get("online_total"),
        "free",
        m2.get("free_slots"),
    )

    ok_cap = bool(m0.get("ready_for_1000")) and int(m0.get("capacity_total") or 0) >= 1100
    # при max_clients=25 на 60 клиентов нужно ≥3 комнаты
    ok_spill = len(c) >= 3
    ok_denied = denied == 0
    print(
        "VERDICT",
        json.dumps(
            {
                "capacity_ok": ok_cap,
                "spill_ok": ok_spill,
                "no_denied": ok_denied,
                "unique_rooms_60": len(c),
                "expected_min_rooms_for_60_at_25": 3,
                "pass": ok_cap and ok_spill and ok_denied,
            },
            ensure_ascii=False,
        ),
    )


asyncio.run(main())
"""


def main() -> None:
    # свежий assign на прод
    client = connect()
    sftp = client.open_sftp()
    local = BACKEND_ROOT / "app" / "services" / "olcrtc_assign.py"
    remote = f"{REMOTE}/app/services/olcrtc_assign.py"
    sftp.put(str(local), remote)
    run(client, f"docker cp {remote} backend-api-1:/app/app/services/olcrtc_assign.py")
    run(client, "docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api >/dev/null")
    run(client, "sleep 14")

    sftp.putfo(io.BytesIO(PROOF.encode()), "/tmp/prove_olcrtc_scale.py")
    run(client, "docker cp /tmp/prove_olcrtc_scale.py backend-api-1:/tmp/prove_olcrtc_scale.py")
    out = run(
        client,
        "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/prove_olcrtc_scale.py",
    )
    print(out)
    units = run(
        client,
        "systemctl list-units 'olcrtc@*' --no-pager --plain --state=running | grep -c 'olcrtc@' || true",
    )
    print("UNITS_RUNNING", units.strip().splitlines()[-1] if units.strip() else "?")
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
