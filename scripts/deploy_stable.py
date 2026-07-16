"""Полный деплой backend: app/ + ai/ + admin-ui/dist → VPS + restart api/nginx."""
from __future__ import annotations

import io
import os
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run

# Bash-тело из fix_tunnel_dnat.py (на VPS нет _deploy_common для python-версии)
from fix_tunnel_dnat import FIX_SH

client = connect()
sftp = client.open_sftp()

for sub in ("app", "ai"):
    base = BACKEND_ROOT / sub
    for root, _, names in os.walk(base):
        for name in names:
            if not name.endswith(".py"):
                continue
            lp = Path(root) / name
            rel = lp.relative_to(BACKEND_ROOT).as_posix()
            rp = f"{REMOTE}/{rel}"
            client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
            sftp.put(str(lp), rp)

dist = BACKEND_ROOT / "admin-ui" / "dist"
if not dist.is_dir():
    sftp.close()
    client.close()
    raise SystemExit("Сначала: cd admin-ui && npm run build")

rdist = f"{REMOTE}/admin-ui/dist"
client.exec_command(f"rm -rf {rdist}/assets && mkdir -p {rdist}/assets")
for root, _, names in os.walk(dist):
    for name in names:
        lp = Path(root) / name
        rel = lp.relative_to(dist).as_posix()
        rp = f"{rdist}/{rel}"
        client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
        sftp.put(str(lp), rp)
        print("ui", rel)

cell_agent_dir = BACKEND_ROOT / "cell-agent"
for name in ("main.py", "standby_runtime.py"):
    cell_agent = cell_agent_dir / name
    if cell_agent.is_file():
        rp = f"{REMOTE}/cell-agent/{name}"
        client.exec_command(f"mkdir -p {REMOTE}/cell-agent")
        sftp.put(str(cell_agent), rp)
        print(f"upload cell-agent/{name}")
    else:
        print(f"WARN: cell-agent/{name} missing locally")

fix_script = BACKEND_ROOT / "scripts" / "fix_tunnel_dnat.py"
if fix_script.is_file():
    rp = f"{REMOTE}/scripts/fix_tunnel_dnat.py"
    client.exec_command(f"mkdir -p {REMOTE}/scripts")
    sftp.put(str(fix_script), rp)
    print("upload scripts/fix_tunnel_dnat.py")
    sftp.putfo(io.BytesIO(FIX_SH.encode()), "/tmp/fix_tunnel_dnat.sh")
    print("upload /tmp/fix_tunnel_dnat.sh")

sftp.close()

script = f"""#!/bin/bash
set -e
cd {REMOTE}
find app ai -name '*.py' | while read f; do docker cp "$f" {CONTAINER}:/app/"$f"; done
docker exec {CONTAINER} mkdir -p /app/cell-agent
for f in cell-agent/main.py cell-agent/standby_runtime.py; do
  if [ -f "$f" ]; then
    docker cp "$f" {CONTAINER}:/app/"$f"
  fi
done
docker exec {CONTAINER} pip install -q paramiko httpx redis disposable-email-domains 2>/dev/null || true
docker compose restart api nginx
sleep 14
bash /tmp/fix_tunnel_dnat.sh
curl -s http://localhost:8000/health
echo
curl -s -o /dev/null -w "admin: %{{http_code}}\\n" http://localhost:8000/
"""
sftp2 = client.open_sftp()
sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_stable.sh")
sftp2.close()
run(client, "bash /tmp/deploy_stable.sh 2>&1", timeout=120)
client.close()
print("Done")
