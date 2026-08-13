"""Деплой olcrtc2-srv на соту Hive (по умолчанию Сота 1 = 87.58.213.193).

  cd backend
  python scripts/deploy_olcrtc2_cell.py
  python scripts/deploy_olcrtc2_cell.py 87.58.213.193

SSH пароль соты — из БД (как deploy_olcrtc_to_hive_cells). Бинарь — локальный
linux amd64: olcrtc2/dist/olcrtc2-srv (собрать заранее).

ЖЁСТКО: не ставить на Улей (132.243.234.162) рядом с wdtt.
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

REMOTE = "/opt/silent-vpn/olcrtc2"
QUEEN_IP = "132.243.234.162"
DEFAULT_CELL = "87.58.213.193"  # Сота 1

UNIT = textwrap.dedent(
    f"""\
    [Unit]
    Description=Silent VPN olcrtc2-srv (Telemost exit)
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    WorkingDirectory={REMOTE}
    EnvironmentFile=-{REMOTE}/olcrtc2.env
    ExecStart={REMOTE}/olcrtc2-srv
    Restart=on-failure
    RestartSec=5
    MemoryMax=512M
    CPUQuota=50%
    LimitNOFILE=65535

    [Install]
    WantedBy=multi-user.target
    """
)

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
        raise SystemExit("REFUSE: do not deploy olcrtc2-srv on WDTT queen")

    bin_local = BACKEND_ROOT / "olcrtc2" / "dist" / "olcrtc2-srv"
    if not bin_local.is_file():
        raise SystemExit(
            f"missing {bin_local} — build:\n"
            "  cd olcrtc2\n"
            "  $env:CGO_ENABLED=0; $env:GOOS='linux'; $env:GOARCH='amd64'\n"
            "  go build -o dist/olcrtc2-srv ./cmd/olcrtc2-srv"
        )

    queen = connect()
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
    if not cells:
        raise SystemExit(f"no cell credentials for {cell_ip}")
    cell = cells[0]
    pwd = cell.get("pwd") or ""
    if not pwd:
        raise SystemExit(f"no SSH password for cell {cell_ip}")

    print(f"=== deploy olcrtc2 → {cell.get('name')} {cell_ip} ===")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(cell_ip, username="root", password=pwd, timeout=25)
    sftp = client.open_sftp()

    def sh(cmd: str) -> str:
        print(f"$ {cmd}")
        return client.exec_command(cmd, timeout=120)[1].read().decode()

    print(sh(f"mkdir -p {REMOTE}"))
    # Binary may be busy (olcrtc2@unit). Stop instances, upload via .new, then replace.
    print(
        sh(
            "systemctl stop 'olcrtc2@*.service' 2>/dev/null || true; "
            "systemctl stop olcrtc2-srv.service 2>/dev/null || true; "
            "sleep 1"
        )
    )
    sftp.put(str(bin_local), f"{REMOTE}/olcrtc2-srv.new")
    print(
        sh(
            f"mv -f {REMOTE}/olcrtc2-srv.new {REMOTE}/olcrtc2-srv; "
            f"chmod +x {REMOTE}/olcrtc2-srv"
        )
    )
    # env template if missing
    try:
        sftp.stat(f"{REMOTE}/olcrtc2.env")
    except OSError:
        env = (
            "OLCRTC2_MODE=telemost\n"
            "OLCRTC2_KEY=\n"
            "OLCRTC2_ROOM=\n"
        )
        sftp.putfo(io.BytesIO(env.encode()), f"{REMOTE}/olcrtc2.env")
    sftp.putfo(io.BytesIO(UNIT.encode()), "/etc/systemd/system/olcrtc2-srv.service")
    print(
        sh(
            f"chmod +x {REMOTE}/olcrtc2-srv; "
            "systemctl daemon-reload; "
            # do not start until ROOM+KEY set — avoid crash loop
            "systemctl enable olcrtc2-srv.service; "
            "systemctl stop olcrtc2-srv.service 2>/dev/null || true; "
            f"test -x {REMOTE}/olcrtc2-srv && echo CELL_OLCRTC2_OK"
        )
    )
    sftp.close()
    client.close()
    print(
        "Done. Set ROOM+KEY on cell:\n"
        f"  nano {REMOTE}/olcrtc2.env\n"
        "  systemctl start olcrtc2-srv\n"
        "Queen wdtt untouched."
    )


if __name__ == "__main__":
    main()
