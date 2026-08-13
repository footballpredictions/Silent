"""Upgrade cell-agent main.py on a Hive cell (keeps existing CELL_AGENT_SECRET).

  cd backend
  python scripts/upgrade_cell_agent_olcrtc2.py
  python scripts/upgrade_cell_agent_olcrtc2.py 87.58.213.193
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, REMOTE, connect, run  # noqa: E402

QUEEN_IP = "132.243.234.162"
DEFAULT_CELL = "87.58.213.193"

CREDS_PY = r"""
import asyncio, json, sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password

async def main():
    want = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    out = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(HiveCell).where(HiveCell.is_queen == False))).scalars().all()
        for r in rows:
            if want and r.public_ip != want:
                continue
            pwd = resolve_ssh_password(r)
            out.append({"ip": r.public_ip, "name": r.name, "pwd": pwd or ""})
    print(json.dumps(out))
asyncio.run(main())
"""


def main() -> None:
    cell_ip = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CELL).strip()
    if cell_ip == QUEEN_IP:
        raise SystemExit("REFUSE: not on queen")
    agent = (BACKEND_ROOT / "cell-agent" / "main.py").read_bytes()
    if b'mode = "wbstream" if prov == "wbstream"' not in agent:
        raise SystemExit("LOCAL cell-agent/main.py missing wbstream mode fix — refuse upgrade")

    queen = connect()
    sftp = queen.open_sftp()
    # Сначала queen: иначе hive auto-upgrade затрёт соту старым cell-agent/main.py
    sftp.putfo(io.BytesIO(agent), f"{REMOTE}/cell-agent/main.py")
    print(f"synced queen {REMOTE}/cell-agent/main.py")
    sftp.putfo(io.BytesIO(CREDS_PY.encode()), "/tmp/olcrtc2_cell_creds.py")
    run(queen, "docker cp /tmp/olcrtc2_cell_creds.py backend-api-1:/tmp/olcrtc2_cell_creds.py")
    _, stdout, _ = queen.exec_command(
        f"docker exec -w /app -e PYTHONPATH=/app backend-api-1 "
        f"python /tmp/olcrtc2_cell_creds.py {cell_ip}",
        timeout=120,
    )
    raw = stdout.read().decode()
    run(queen, "rm -f /tmp/olcrtc2_cell_creds.py; docker exec backend-api-1 rm -f /tmp/olcrtc2_cell_creds.py")
    sftp.close()
    queen.close()

    line = [ln for ln in raw.splitlines() if ln.strip().startswith("[")][-1]
    cells = json.loads(line)
    if not cells or not cells[0].get("pwd"):
        raise SystemExit(f"no SSH password for {cell_ip}")
    pwd = cells[0]["pwd"]

    print(f"=== upgrade cell-agent → {cell_ip} ===")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(cell_ip, username="root", password=pwd, timeout=25)
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(agent), "/opt/silent-vpn/cell-agent/main.py")
    sftp.close()
    _, so, se = client.exec_command(
        "mkdir -p /opt/silent-vpn/olcrtc2/env.d; "
        "rm -rf /opt/silent-vpn/cell-agent/__pycache__; "
        "systemctl restart silent-cell-agent; sleep 2; "
        "systemctl is-active silent-cell-agent; "
        "grep -n 'mode = .wbstream. if prov' /opt/silent-vpn/cell-agent/main.py | head -3; "
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9100/docs || "
        "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9100/v1/status || echo fail",
        timeout=60,
    )
    print(so.read().decode(errors="replace"))
    err = se.read().decode(errors="replace")
    if err.strip():
        print(err[:400])
    client.close()
    print("CELL_AGENT_OLCRTC2_OK")


if __name__ == "__main__":
    main()
