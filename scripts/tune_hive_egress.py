"""Применить egress PMTU/TTL на Улей и опционально соту 3. wdtt не рестартит.

  cd backend
  python scripts/tune_hive_egress.py
  python scripts/tune_hive_egress.py --also-cell3
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402
from app.services.hive_egress_tune import tune_script  # noqa: E402

CELL3 = "192.177.26.38"

CREDS_PY = r"""
import asyncio, json, sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password

async def main():
    want = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(HiveCell).where(HiveCell.is_queen == False))).scalars().all()
        for r in rows:
            if want and (r.public_ip or "").strip() != want:
                continue
            pwd = resolve_ssh_password(r)
            print(json.dumps({"ip": r.public_ip, "name": r.name, "ok": bool(pwd)}))
            if pwd:
                print("PWD_LINE " + pwd)
            return
    print(json.dumps({"ok": False}))
asyncio.run(main())
"""


def _exec(client, script: str, timeout: int = 90) -> str:
    _, stdout, stderr = client.exec_command(script, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + (("\nSTDERR\n" + err) if err.strip() else "")


def _apply(client, label: str) -> None:
    script = tune_script()
    sftp = client.open_sftp()
    with sftp.file("/tmp/silent_egress_pmtu.sh", "w") as f:
        f.write(script)
    sftp.close()
    print(f"=== apply {label} ===")
    print(_exec(client, "bash /tmp/silent_egress_pmtu.sh"))


def _cell3_client(queen) -> paramiko.SSHClient | None:
    api = "backend-api-1"
    sftp = queen.open_sftp()
    with sftp.file("/tmp/egress_cell_creds.py", "w") as f:
        f.write(CREDS_PY)
    sftp.close()
    _, stdout, _ = queen.exec_command(f"docker cp /tmp/egress_cell_creds.py {api}:/tmp/egress_cell_creds.py")
    stdout.channel.recv_exit_status()
    _, stdout, _ = queen.exec_command(
        f"docker exec -w /app -e PYTHONPATH=/app {api} python /tmp/egress_cell_creds.py {CELL3}",
        timeout=60,
    )
    raw = stdout.read().decode("utf-8", errors="replace")
    pwd = ""
    meta: dict = {}
    for line in raw.splitlines():
        if line.startswith("PWD_LINE "):
            pwd = line[len("PWD_LINE ") :].strip()
        elif line.startswith("{"):
            try:
                meta = json.loads(line)
            except json.JSONDecodeError:
                pass
    if not pwd:
        print("cell3: no ssh password")
        return None
    print(f"cell3 ssh {meta.get('name') or CELL3} ok")
    cell = paramiko.SSHClient()
    cell.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cell.connect(CELL3, username="root", password=pwd, timeout=20)
    return cell


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--also-cell3", action="store_true")
    args = parser.parse_args()
    queen = connect(timeout=25, attempts=3, pause=4)
    _apply(queen, "hive")
    if args.also_cell3:
        cell = _cell3_client(queen)
        if cell is not None:
            try:
                _apply(cell, "cell3")
            finally:
                cell.close()
    queen.close()


if __name__ == "__main__":
    main()
