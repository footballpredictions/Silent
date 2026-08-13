"""Деплой Playwright host-provision на СОТУ (не Улей).

  cd backend
  python scripts/deploy_olcrtc2_host_provision_cell.py
  python scripts/deploy_olcrtc2_host_provision_cell.py 87.58.213.193

Слушает 0.0.0.0:9101, UFW только с IP Улья. ЖЁСТКО: не на 132.243.234.162.
"""
from __future__ import annotations

import io
import json
import sys
import textwrap
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, connect, run  # noqa: E402

QUEEN_IP = "132.243.234.162"
DEFAULT_CELL = "87.58.213.193"
REMOTE_BASE = "/opt/silent-vpn/olcrtc2"
REMOTE_HP = f"{REMOTE_BASE}/host-provision"
REMOTE_STATES = f"{REMOTE_BASE}/agent_states"
UNIT = "/etc/systemd/system/silent-olcrtc2-host-provision.service"
LOCAL_SERVER = BACKEND_ROOT / "scripts" / "olcrtc_host_provision_server.py"
LOCAL_PROVISION = BACKEND_ROOT / "ai" / "olcrtc_room_provision.py"

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


def _unit(secret_line: str) -> str:
    return textwrap.dedent(
        f"""\
        [Unit]
        Description=Silent VPN olcrtc2 host Playwright provision (CELL only)
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        WorkingDirectory={REMOTE_HP}
        Environment=OLCRTC_HOST_PROVISION_BIND=0.0.0.0
        Environment=OLCRTC_HOST_PROVISION_PORT=9101
        Environment=OLCRTC_HOST_PROVISION_STATE_DIR={REMOTE_STATES}
        Environment=OLCRTC_BACKEND_ROOT={REMOTE_HP}
        Environment=OLCRTC_HOST_CREATE_PARALLEL=1
        {secret_line}
        ExecStart={REMOTE_HP}/venv/bin/python {REMOTE_HP}/olcrtc_host_provision_server.py
        Restart=on-failure
        RestartSec=5
        MemoryHigh=1500M
        MemoryMax=2500M
        TasksMax=200

        [Install]
        WantedBy=multi-user.target
        """
    )


def main() -> None:
    cell_ip = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CELL).strip()
    if cell_ip == QUEEN_IP:
        raise SystemExit("REFUSE: Playwright host-provision must NOT run on WDTT queen")
    if not LOCAL_SERVER.is_file() or not LOCAL_PROVISION.is_file():
        raise SystemExit("missing host provision sources")

    queen = connect()
    # INTERNAL_API_SECRET from queen .env
    _, so, _ = queen.exec_command(
        "grep -E '^INTERNAL_API_SECRET=' /opt/silent-vpn/backend/.env | head -1",
        timeout=30,
    )
    secret_env = (so.read().decode() or "").strip()
    if not secret_env.startswith("INTERNAL_API_SECRET="):
        secret_env = ""

    sftp = queen.open_sftp()
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

    print(f"=== olcrtc2 host-provision → cell {cell_ip} ===")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(cell_ip, username="root", password=pwd, timeout=30)
    sftp = client.open_sftp()

    def sh(cmd: str, timeout: int = 600) -> str:
        print(f"$ {cmd[:120]}…")
        _, out, err = client.exec_command(cmd, timeout=timeout)
        o = out.read().decode(errors="replace")
        e = err.read().decode(errors="replace")
        if e.strip():
            print(e[:400])
        return o

    sh(f"mkdir -p {REMOTE_HP}/ai {REMOTE_STATES}")
    sftp.put(str(LOCAL_SERVER), f"{REMOTE_HP}/olcrtc_host_provision_server.py")
    sftp.put(str(LOCAL_PROVISION), f"{REMOTE_HP}/ai/olcrtc_room_provision.py")
    sftp.putfo(io.BytesIO(b"# stub\n"), f"{REMOTE_HP}/ai/__init__.py")
    if secret_env:
        sftp.putfo(io.BytesIO((secret_env + "\n").encode()), f"{REMOTE_HP}/.env")
    sftp.close()

    secret_line = f"EnvironmentFile=-{REMOTE_HP}/.env" if secret_env else ""
    unit_body = _unit(secret_line)
    # write unit via cat
    sh(
        f"cat > {UNIT} <<'EOF'\n{unit_body}\nEOF\n"
        f"set -e\n"
        f"apt-get install -y -qq python3-venv python3-pip >/dev/null 2>&1 || true\n"
        f"cd {REMOTE_HP}\n"
        f"if [ ! -x venv/bin/python ]; then rm -rf venv; python3 -m venv venv; fi\n"
        f"./venv/bin/pip install -q --upgrade pip\n"
        f"./venv/bin/pip install -q 'playwright>=1.40' httpx\n"
        f"./venv/bin/playwright install-deps chromium || true\n"
        f"./venv/bin/playwright install chromium\n"
        f"systemctl daemon-reload\n"
        f"systemctl enable silent-olcrtc2-host-provision\n"
        f"systemctl restart silent-olcrtc2-host-provision\n"
        f"ufw allow from {QUEEN_IP} to any port 9101 proto tcp comment 'olcrtc2-host-from-queen' || true\n"
        f"sleep 2\n"
        f"systemctl is-active silent-olcrtc2-host-provision\n"
        f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:9101/v1/status || true\n"
        f"echo CELL_HOST_PROVISION_OK\n",
        timeout=900,
    )
    client.close()
    print("Done. Queen wdtt untouched. Create URL: http://%s:9101" % cell_ip)


if __name__ == "__main__":
    main()
