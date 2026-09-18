"""Upgrade cell-agent on Hive cells (keeps existing CELL_AGENT_SECRET).

SSH сот — с Улья, не из РФ (TCP к части сот с дома таймаут).
wdtt / api / nginx не рестартим.

  cd backend
  python scripts/upgrade_cell_agent_olcrtc2.py --all
  python scripts/upgrade_cell_agent_olcrtc2.py 87.58.213.193
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, REMOTE, connect, run  # noqa: E402

QUEEN_IP = "89.125.188.100"
DEFAULT_CELL = "87.58.213.193"

UPGRADE_FROM_HIVE = r"""
import asyncio
import sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password
from app.services.hive_provision_service import upgrade_cell_agent_via_ssh

async def main():
    want = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    async with AsyncSessionLocal() as db:
        rows = list((await db.execute(select(HiveCell).where(HiveCell.is_queen == False))).scalars().all())
    for r in rows:
        ip = (r.public_ip or "").strip()
        if want and ip != want:
            continue
        pwd = resolve_ssh_password(r)
        name = r.name or ip
        if not ip or not pwd:
            print(f"SKIP {name} no-ssh")
            continue
        try:
            upgrade_cell_agent_via_ssh(
                ip,
                pwd,
                link_capacity_mbps=float(r.link_capacity_mbps or 1000),
            )
            print(f"OK {name} {ip}")
        except Exception as e:
            print(f"FAIL {name} {type(e).__name__}: {e}")

asyncio.run(main())
"""


def main() -> None:
    arg = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CELL).strip()
    cell_ip = "" if arg in ("--all", "all") else arg
    if cell_ip == QUEEN_IP:
        raise SystemExit("REFUSE: not on queen")
    agent = (BACKEND_ROOT / "cell-agent" / "main.py").read_bytes()
    standby = (BACKEND_ROOT / "cell-agent" / "standby_runtime.py").read_bytes()
    if b"def queen_proxy_urls(" not in standby:
        raise SystemExit("LOCAL standby_runtime.py missing queen_proxy_urls — refuse upgrade")

    queen = connect()
    sftp = queen.open_sftp()
    # Сначала queen: иначе hive auto-upgrade затрёт соту старым cell-agent.
    sftp.putfo(io.BytesIO(agent), f"{REMOTE}/cell-agent/main.py")
    sftp.putfo(io.BytesIO(standby), f"{REMOTE}/cell-agent/standby_runtime.py")
    print(f"synced queen {REMOTE}/cell-agent/main.py + standby_runtime.py")
    sftp.putfo(io.BytesIO(UPGRADE_FROM_HIVE.encode()), "/tmp/cell_agent_upgrade_from_hive.py")
    sftp.close()
    run(queen, "docker cp /tmp/cell_agent_upgrade_from_hive.py backend-api-1:/tmp/cell_agent_upgrade_from_hive.py")
    want = cell_ip
    _, stdout, stderr = queen.exec_command(
        f"docker exec -w /app -e PYTHONPATH=/app backend-api-1 "
        f"python /tmp/cell_agent_upgrade_from_hive.py {want}",
        timeout=600,
    )
    print(stdout.read().decode(errors="replace"))
    err = stderr.read().decode(errors="replace")
    if err.strip():
        print(err[:800])
    run(
        queen,
        "rm -f /tmp/cell_agent_upgrade_from_hive.py; "
        "docker exec backend-api-1 rm -f /tmp/cell_agent_upgrade_from_hive.py",
    )
    queen.close()
    print("CELL_AGENT_OLCRTC2_OK")


if __name__ == "__main__":
    main()
