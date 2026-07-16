"""Восстановить app/ai в контейнере после force-recreate (не трогает docker-compose/UFW)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, connect, run  # noqa: E402

RESTORE_SH = """#!/bin/bash
set -e
cd /opt/silent-vpn/backend
echo "=== sync app+ai from host into container ==="
find app ai -name '*.py' | while read -r f; do
  docker cp "$f" backend-api-1:/app/"$f"
done
echo "=== deps (image often missing httpx after recreate) ==="
docker exec backend-api-1 pip install -q paramiko httpx redis disposable-email-domains 2>/dev/null || true
echo "=== restart api ==="
docker compose restart api
sleep 14
python3 scripts/fix_tunnel_dnat.py 2>&1 || true
echo "=== verify ==="
docker exec backend-api-1 test -f /app/app/api/hive.py && echo "hive.py OK"
curl -sf http://127.0.0.1:8000/api/health && echo " health OK"
hive_code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/admin/hive/cells)
echo "hive/cells HTTP ${hive_code} (expect 401 without token)"
if [ "${hive_code}" = "404" ]; then
  echo "ERROR: hive routes still missing"
  exit 1
fi
"""


def upload_local_py(client) -> None:
    """Also push latest .py from workspace to host (in case host is behind)."""
    sftp = client.open_sftp()
    for sub in ("app", "ai"):
        base = BACKEND_ROOT / sub
        for root, _, names in os.walk(base):
            for name in names:
                if not name.endswith(".py"):
                    continue
                lp = Path(root) / name
                rel = lp.relative_to(BACKEND_ROOT).as_posix()
                rp = f"/opt/silent-vpn/backend/{rel}"
                parent = os.path.dirname(rp).replace("\\", "/")
                client.exec_command(f"mkdir -p {parent}")
                sftp.put(str(lp), rp)
    sftp.close()


import os  # noqa: E402


def main() -> None:
    client = connect()
    print("Uploading latest Python from workspace...")
    upload_local_py(client)
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(RESTORE_SH.encode()), "/tmp/restore_api_code.sh")
    sftp.chmod("/tmp/restore_api_code.sh", 0o755)
    sftp.close()
    run(client, "bash /tmp/restore_api_code.sh 2>&1", timeout=180)
    client.close()
    print("Restore complete.")


if __name__ == "__main__":
    main()
