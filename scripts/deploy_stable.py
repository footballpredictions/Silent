"""Полный деплой backend: app/ + ai/ + admin-ui/dist → хост VPS + restart api/nginx.

Живой Python — volume `./app` и `./ai` (как admin-ui). Recreate контейнера не откатывает код.
Не трогает wdtt.service.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run
from fix_tunnel_dnat import FIX_SH

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".pytest_cache"}


def _upload_py_tree(sftp, client, sub: str) -> int:
    base = BACKEND_ROOT / sub
    n = 0
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if not name.endswith(".py"):
                continue
            lp = Path(root) / name
            rel = lp.relative_to(BACKEND_ROOT).as_posix()
            rp = f"{REMOTE}/{rel}"
            client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
            sftp.put(str(lp), rp)
            n += 1
    print(f"upload {sub}/: {n} py")
    return n


def main() -> None:
    dist = BACKEND_ROOT / "admin-ui" / "dist"
    if not dist.is_dir() or not any(dist.iterdir()):
        raise SystemExit("Сначала: cd admin-ui && npm run build")

    client = connect()
    sftp = client.open_sftp()

    _upload_py_tree(sftp, client, "app")
    _upload_py_tree(sftp, client, "ai")

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

    client.exec_command(f"mkdir -p {REMOTE}/scripts")
    for name in ("fix_tunnel_dnat.py", "_deploy_common.py"):
        lp = BACKEND_ROOT / "scripts" / name
        if lp.is_file():
            sftp.put(str(lp), f"{REMOTE}/scripts/{name}")
            print(f"upload scripts/{name}")
    sftp.putfo(io.BytesIO(FIX_SH.encode()), "/tmp/fix_tunnel_dnat.sh")
    print("upload /tmp/fix_tunnel_dnat.sh")

    compose_local = BACKEND_ROOT / "docker-compose.yml"
    sftp.put(str(compose_local), f"{REMOTE}/docker-compose.yml")
    print("upload docker-compose.yml")

    static_dir = BACKEND_ROOT / "static"
    client.exec_command(f"mkdir -p {REMOTE}/static/theme")
    for name in ("logo.png", "logo-32.png", "vk-agent-oauth.html"):
        lp = static_dir / name
        if lp.is_file():
            sftp.put(str(lp), f"{REMOTE}/static/{name}")
            print(f"static/{name}")

    sftp.close()

    # Код уже на хосте. up -d api --no-deps recreate только если compose изменился;
    # после volume ./app и ./ai recreate безопасен. wdtt не трогаем.
    script = f"""#!/bin/bash
set -e
cd {REMOTE}
echo "=== compose apply (no-deps, never wdtt) ==="
docker compose up -d api --no-deps
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if docker inspect -f '{{{{.State.Running}}}}' {CONTAINER} 2>/dev/null | grep -q true; then
    break
  fi
  sleep 1
done
docker exec {CONTAINER} pip install -q paramiko httpx redis disposable-email-domains 2>/dev/null || true
docker compose restart api nginx
sleep 14
echo "=== mounts ==="
n=$(docker inspect -f '{{{{range .Mounts}}}}{{{{println .Destination}}}}{{{{end}}}}' {CONTAINER} | grep -cE '^/app/(app|ai)$' || true)
echo "app/ai mounts: $n (need 2)"
if [ "$n" != "2" ]; then
  echo "ERROR: app/ai volumes missing after up" >&2
  docker inspect -f '{{{{json .Mounts}}}}' {CONTAINER}
  exit 1
fi
echo "=== tunnel DNAT ==="
bash /tmp/fix_tunnel_dnat.sh
echo "=== verify ==="
curl -sf http://127.0.0.1:8000/api/health && echo " health OK"
curl -sf http://127.0.0.1:8000/health && echo " /health OK" || true
admin=$(curl -s -o /dev/null -w "%{{http_code}}" http://127.0.0.1:8000/)
echo "admin: $admin"
hive=$(curl -s -o /dev/null -w "%{{http_code}}" -H "Host: 132-243-234-162.nip.io" http://127.0.0.1:8000/api/admin/hive/cells)
echo "hive/cells HTTP $hive (expect 401)"
if [ "$hive" = "404" ]; then
  echo "ERROR: hive routes missing" >&2
  exit 1
fi
wdtt=$(systemctl is-active wdtt.service || true)
echo "wdtt: $wdtt"
if [ "$wdtt" != "active" ]; then
  echo "ERROR: wdtt is not active (script did not restart it)" >&2
  exit 1
fi
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_stable.sh")
    sftp2.close()
    run(client, "bash /tmp/deploy_stable.sh 2>&1", timeout=180)
    client.close()
    print("Done")


if __name__ == "__main__":
    main()
