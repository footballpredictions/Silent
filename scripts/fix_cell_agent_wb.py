"""Verify + force-upgrade cell-agent WB apply on Cell 2, then heal rooms."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, connect, run  # noqa: E402

CELL = "78.17.74.27"

CREDS = r"""
import asyncio, json, sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password
async def main():
    async with AsyncSessionLocal() as db:
        r = (await db.execute(select(HiveCell).where(HiveCell.public_ip == sys.argv[1]))).scalar_one()
        print(json.dumps({"pwd": resolve_ssh_password(r) or ""}))
asyncio.run(main())
"""


def main() -> None:
    agent = (BACKEND_ROOT / "cell-agent" / "main.py").read_bytes()
    # sanity: local file must contain wbstream mode write
    if b'mode = "wbstream" if prov == "wbstream"' not in agent:
        raise SystemExit("LOCAL cell-agent/main.py missing wbstream mode fix")

    queen = connect()
    sftp = queen.open_sftp()
    sftp.putfo(io.BytesIO(CREDS.encode()), "/tmp/c2pwd.py")
    sftp.close()
    run(queen, "docker cp /tmp/c2pwd.py backend-api-1:/tmp/c2pwd.py")
    raw = run(
        queen,
        f"docker exec -e PYTHONPATH=/app -w /app backend-api-1 python /tmp/c2pwd.py {CELL}",
    )
    queen.close()
    pwd = json.loads([ln for ln in raw.splitlines() if ln.strip().startswith("{")][-1])["pwd"]
    if not pwd:
        raise SystemExit("no pwd")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CELL, username="root", password=pwd, timeout=25)

    def sh(cmd: str, timeout: int = 90) -> str:
        _, o, e = c.exec_command(cmd, timeout=timeout)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print("=== before ===")
    print(sh("systemctl cat silent-cell-agent | sed -n '1,35p'"))
    print(sh("grep -n 'OLCRTC2_MODE\\|wbstream requires\\|auth_token' /opt/silent-vpn/cell-agent/main.py | head -20"))

    sftp = c.open_sftp()
    sftp.putfo(io.BytesIO(agent), "/opt/silent-vpn/cell-agent/main.py")
    sftp.close()
    print(sh(
        "systemctl restart silent-cell-agent; sleep 2; "
        "systemctl is-active silent-cell-agent; "
        "grep -n 'mode = .wbstream. if prov' /opt/silent-vpn/cell-agent/main.py | head -3"
    ))

    # Stop crash-looping units; wipe env; queen heal will recreate
    print(sh(
        "systemctl stop 'olcrtc2@*.service' 2>/dev/null || true; "
        "rm -f /opt/silent-vpn/olcrtc2/env.d/*.env; "
        "echo wiped_env; ls /opt/silent-vpn/olcrtc2/env.d || true"
    ))
    c.close()
    print("CELL_AGENT_FIXED")


if __name__ == "__main__":
    main()
