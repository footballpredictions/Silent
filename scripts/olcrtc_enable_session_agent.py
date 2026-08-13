"""Enable olcrtc room agent in session-mode on prod (one-shot)."""
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
from ai.olcrtc_room_agent import load_agent_state, save_agent_state, heal_rooms

async def main():
    async with AsyncSessionLocal() as db:
        st = await load_agent_state(db)
        st.enabled = True
        st.session_mode = True
        st.max_clients = 1
        st.min_free_per_slot = 0
        st.min_rooms_per_slot = 0
        st.bootstrap_warm = 0
        st.auto_apply_yaml = True
        st.auto_units = True
        await save_agent_state(db, st)
        print("agent enabled session_mode=", st.session_mode, "enabled=", st.enabled)
        out = await heal_rooms(db, force=True)
        err = out.last_error[:200] if out.last_error else "-"
        print("heal last_error", err)
        print("run_log", out.run_log[-8:])

asyncio.run(main())
"""
    sftp.putfo(io.BytesIO(py.encode()), "/tmp/olcrtc_enable_agent.py")
    run(client, "docker cp /tmp/olcrtc_enable_agent.py backend-api-1:/tmp/olcrtc_enable_agent.py")
    print(
        run(
            client,
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/olcrtc_enable_agent.py",
        )
    )
    print(
        run(
            client,
            "systemctl is-active silent-olcrtc-host-provision; "
            "systemctl list-units 'olcrtc@*' --no-legend 2>/dev/null | head -15 || true",
        )
    )
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
