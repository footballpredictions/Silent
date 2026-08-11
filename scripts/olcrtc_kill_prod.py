"""Полностью погасить olcrtc на Улье: units, host-provision, agent, providers."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402


def main() -> None:
    c = connect()
    try:
        run(c, "systemctl stop silent-olcrtc-host-provision 2>/dev/null; systemctl disable silent-olcrtc-host-provision 2>/dev/null; true")
        run(c, "systemctl stop silent-olcrtc-proxy 2>/dev/null; systemctl disable silent-olcrtc-proxy 2>/dev/null; true")
        run(
            c,
            "systemctl list-units 'olcrtc@*' --all --no-legend | awk '{print $1}' | "
            "while read u; do [ -n \"$u\" ] && systemctl disable --now \"$u\" 2>/dev/null; done; true",
        )
        run(c, "systemctl list-units 'olcrtc@*' --state=running --no-legend | wc -l")
        run(c, "systemctl is-active silent-olcrtc-host-provision silent-olcrtc-proxy 2>/dev/null; true")

        py = r'''
import asyncio, json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import AppSetting
from app.services.olcrtc_settings import load_olcrtc_settings, save_olcrtc_settings
from ai.olcrtc_room_agent import load_agent_state, save_agent_state

async def main():
    async with AsyncSessionLocal() as db:
        st = await load_agent_state(db)
        st.enabled = False
        st.session_mode = True
        st.min_free_per_slot = 0
        st.min_rooms_per_slot = 0
        await save_agent_state(db, st)
        settings = await load_olcrtc_settings(db)
        for name, p in list(settings.providers.items()):
            p.enabled = False
            settings.providers[name] = p
        settings.enabled = False
        await save_olcrtc_settings(db, settings)
        # clear sticky so clients don't stick to dead rooms
        from sqlalchemy import text
        r1 = await db.execute(text("DELETE FROM olcrtc_room_sticky"))
        r2 = await db.execute(text("UPDATE olcrtc_rooms SET status='offline' WHERE status IN ('active','provisioning','error','draining')"))
        await db.commit()
        print("agent_enabled", st.enabled)
        print("providers", {n: p.enabled for n, p in settings.providers.items()})
        print("sticky_deleted", r1.rowcount, "rooms_offline", r2.rowcount)

asyncio.run(main())
'''
        sftp = c.open_sftp()
        remote = "/tmp/olcrtc_kill.py"
        with sftp.file(remote, "w") as f:
            f.write(py)
        sftp.close()
        run(c, "docker cp /tmp/olcrtc_kill.py backend-api-1:/tmp/olcrtc_kill.py")
        run(c, "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/olcrtc_kill.py")
        run(c, "ps -eo pid,pcpu,comm --sort=-pcpu | head -12")
    finally:
        c.close()


if __name__ == "__main__":
    main()
