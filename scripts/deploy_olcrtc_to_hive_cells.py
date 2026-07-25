"""Залить olcrtc + cell-agent на worker-соты (SSH пароль из БД через API-контейнер).

  cd backend
  python scripts/deploy_olcrtc_to_hive_cells.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import textwrap
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, connect, run  # noqa: E402

REMOTE_OLCRTC = "/opt/silent-vpn/olcrtc"
UNIT = textwrap.dedent(
    f"""\
    [Unit]
    Description=Silent VPN olcrtc srv (%i)
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    WorkingDirectory={REMOTE_OLCRTC}
    ExecStart={REMOTE_OLCRTC}/olcrtc {REMOTE_OLCRTC}/server-%i.yaml
    Restart=on-failure
    RestartSec=5
    LimitNOFILE=65535

    [Install]
    WantedBy=multi-user.target
    """
)

CREDS_PY = r"""
import asyncio, json
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password

async def main():
    out = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(HiveCell).where(HiveCell.is_queen == False))).scalars().all()
        for r in rows:
            pwd = resolve_ssh_password(r)
            out.append({"id": str(r.id), "ip": r.public_ip, "status": r.status, "pwd": pwd or ""})
    print(json.dumps(out))
asyncio.run(main())
"""


def _ssh_cell(ip: str, password: str, binary_local: Path, agent_local: Path | None) -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username="root", password=password, timeout=25)
    sftp = client.open_sftp()
    run_c = lambda cmd: client.exec_command(cmd, timeout=120)[1].read().decode()
    print(run_c(f"mkdir -p {REMOTE_OLCRTC}/data /opt/silent-vpn/cell-agent"))
    sftp.put(str(binary_local), f"{REMOTE_OLCRTC}/olcrtc")
    sftp.putfo(io.BytesIO(UNIT.encode()), "/etc/systemd/system/olcrtc@.service")
    if agent_local and agent_local.is_file():
        sftp.put(str(agent_local), "/opt/silent-vpn/cell-agent/main.py")
    print(
        run_c(
            f"chmod +x {REMOTE_OLCRTC}/olcrtc; systemctl daemon-reload; "
            "systemctl restart silent-cell-agent 2>/dev/null || "
            "systemctl restart cell-agent 2>/dev/null || true; "
            "test -x /opt/silent-vpn/olcrtc/olcrtc && echo CELL_OLCRTC_OK"
        )
    )
    sftp.close()
    client.close()


def main() -> None:
    queen = connect()
    sftp = queen.open_sftp()
    # скачать бинарь с Улья
    with tempfile.TemporaryDirectory() as td:
        local_bin = Path(td) / "olcrtc"
        sftp.get(f"{REMOTE_OLCRTC}/olcrtc", str(local_bin))
        print("got binary", local_bin.stat().st_size)

        sftp.putfo(io.BytesIO(CREDS_PY.encode()), "/tmp/cell_creds.py")
        run(queen, "docker cp /tmp/cell_creds.py backend-api-1:/tmp/cell_creds.py")
        # не печатать stdout (там пароли) — читаем канал напрямую
        _, stdout, _ = queen.exec_command(
            "docker exec -w /app -e PYTHONPATH=/app backend-api-1 python /tmp/cell_creds.py",
            timeout=120,
        )
        raw = stdout.read().decode()
        line = [ln for ln in raw.splitlines() if ln.strip().startswith("[")][-1]
        cells = json.loads(line)
        # зачистка файла с паролями на сервере
        run(queen, "rm -f /tmp/cell_creds.py; docker exec backend-api-1 rm -f /tmp/cell_creds.py")
        print("cells", [{"ip": c.get("ip"), "status": c.get("status"), "has_pwd": bool(c.get("pwd"))} for c in cells])
        agent = BACKEND_ROOT / "cell-agent" / "main.py"
        ok = 0
        for cell in cells:
            ip = (cell.get("ip") or "").strip()
            pwd = cell.get("pwd") or ""
            if not ip or not pwd:
                print("skip", ip, "no pwd")
                continue
            print(f"=== cell {ip} ===")
            try:
                _ssh_cell(ip, pwd, local_bin, agent if agent.is_file() else None)
                ok += 1
            except Exception as e:
                print("FAIL", ip, type(e).__name__, str(e)[:200])
        print(f"Deployed ok={ok}/{len(cells)}")
        if ok < 1:
            raise SystemExit(1)
    sftp.close()
    queen.close()
    print("Done")


if __name__ == "__main__":
    main()
