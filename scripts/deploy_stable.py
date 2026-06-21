"""Полный деплой backend: app/ + ai/ + admin-ui/dist → VPS + restart api/nginx."""
from __future__ import annotations

import io
import os
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run

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

fix_script = BACKEND_ROOT / "scripts" / "fix_tunnel_dnat.py"
if fix_script.is_file():
    rp = f"{REMOTE}/scripts/fix_tunnel_dnat.py"
    client.exec_command("mkdir -p scripts")
    sftp.put(str(fix_script), rp)
    print("upload scripts/fix_tunnel_dnat.py")

sftp.close()

script = f"""#!/bin/bash
set -e
cd {REMOTE}
find app ai -name '*.py' | while read f; do docker cp "$f" {CONTAINER}:/app/"$f"; done
docker compose restart api nginx
sleep 14
python3 scripts/fix_tunnel_dnat.py
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
