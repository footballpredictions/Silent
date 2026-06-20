"""Деплой Hive (Улей): app + cell-agent + pip paramiko + admin-ui."""
from __future__ import annotations

import io
import os
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run

client = connect()
sftp = client.open_sftp()

hive_files = [
    "app/models/hive_cell.py",
    "app/models/device.py",
    "app/models/__init__.py",
    "app/services/hive_service.py",
    "app/services/hive_load.py",
    "app/services/proc_stats.py",
    "app/services/hive_provision_service.py",
    "app/services/vpn_service.py",
    "app/services/build_agent_service.py",
    "app/schemas/hive.py",
    "app/api/hive.py",
    "app/api/vpn.py",
    "app/main.py",
    "app/config.py",
    "docker-compose.yml",
    "requirements.txt",
    "cell-agent/main.py",
]

for rel in hive_files:
    lp = BACKEND_ROOT / rel.replace("/", os.sep)
    if not lp.is_file():
        print("skip (missing)", rel)
        continue
    rp = f"{REMOTE}/{rel.replace(chr(92), '/')}"
    client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
    sftp.put(str(lp), rp)
    print("upload", rel)

dist = BACKEND_ROOT / "admin-ui" / "dist"
if dist.is_dir():
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
else:
    print("WARN: admin-ui/dist missing — run npm run build")

sftp.close()

script = f"""#!/bin/bash
set -e
cd {REMOTE}
for f in {' '.join(hive_files)}; do
  [ -f "$f" ] && docker cp "$f" {CONTAINER}:/app/"$f"
done
docker exec {CONTAINER} mkdir -p /app/cell-agent
docker cp cell-agent/main.py {CONTAINER}:/app/cell-agent/main.py 2>/dev/null || true
docker exec {CONTAINER} pip install -q paramiko httpx 2>/dev/null || true
docker compose restart api nginx
sleep 16
curl -s http://localhost:8000/api/health
echo
code=$(curl -s -o /dev/null -w "%{{http_code}}" -X POST http://localhost:8000/api/admin/hive/cells/auto -H "Content-Type: application/json" -d '{{}}')
echo "hive POST /cells/auto: HTTP $code (expect 401/403/422, not 405)"
if [ "$code" = "405" ]; then echo "ERROR: hive routes missing in container"; exit 1; fi
"""
sftp2 = client.open_sftp()
sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_hive.sh")
sftp2.close()
run(client, "bash /tmp/deploy_hive.sh 2>&1", timeout=180)
client.close()
print("Done — откройте админку → Улей")
