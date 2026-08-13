"""Prod diag: rooms + unit health."""
from __future__ import annotations

import io
import sys
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
from app.services.olcrtc_settings import load_olcrtc_settings
from ai.olcrtc_host_provision_client import host_unit_health, host_provision_status
from ai.olcrtc_room_agent import load_agent_state

async def main():
    st = await host_provision_status()
    print("host reachable=", st.get("reachable"), "pw=", st.get("playwright"), "tm=", st.get("telemost_state"))
    async with AsyncSessionLocal() as db:
        ag = await load_agent_state(db)
        print("agent enabled=", ag.enabled, "session=", ag.session_mode, "max=", ag.max_clients)
        settings = await load_olcrtc_settings(db)
        for n, p in settings.providers.items():
            print("provider", n, "enabled=", p.enabled, "rooms_json=", [(s.id, (s.url or "")[:24], s.max_clients) for s in (p.rooms or [])])
        print("metrics", await pool_metrics(db))
        for r in await list_rooms(db):
            h = await host_unit_health(r.unit_name)
            print(
                r.provider, r.unit_name, r.slot_label, r.status,
                "online", r.online_count, "/", r.max_clients,
                "room", (r.room_url or "")[:36],
                "healthy", h.get("healthy"), "link", h.get("link_connected"), "active", h.get("active"),
            )

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/olcrtc_diag2.py")
    run(client, "docker cp /tmp/olcrtc_diag2.py backend-api-1:/tmp/olcrtc_diag2.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/olcrtc_diag2.py",
        )
    )
    print(
        run(
            client,
            "systemctl list-units 'olcrtc@*' --no-legend 2>/dev/null | head -30 || true",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
