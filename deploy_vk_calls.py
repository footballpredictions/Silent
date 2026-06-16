"""One-shot deploy: VK Calls auth + admin UI."""
import io
import os
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "132.243.234.162"
USER = "root"
PASS = "3txvDbnJvVaZg"
LOCAL = os.path.join(os.path.dirname(__file__), "backend")
REMOTE = "/opt/silent-vpn/backend"

FILES = [
    "app/services/vk_calls_auth.py",
    "app/services/vk_agent_auth.py",
    "app/api/admin.py",
    "app/config.py",
    "app/services/subscription_service.py",
    "app/api/vk_auth.py",
    "app/services/vk_id_service.py",
    "ai/vk_manager.py",
    "ai/tunnel_monitor.py",
    "app/services/user_hash_service.py",
]


def main() -> None:
    dist = os.path.join(LOCAL, "admin-ui", "dist")
    if not os.path.isdir(dist):
        print("Build admin-ui first")
        sys.exit(1)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=30)
    sftp = client.open_sftp()

    for rel in FILES:
        local = os.path.join(LOCAL, rel.replace("/", os.sep))
        remote = f"{REMOTE}/{rel}"
        sftp.put(local, remote)
        print(f"uploaded {rel}")

    remote_dist = f"{REMOTE}/admin-ui/dist"
    client.exec_command(f"mkdir -p {remote_dist}")
    for root, _, fnames in os.walk(dist):
        for name in fnames:
            lp = os.path.join(root, name)
            rel = os.path.relpath(lp, dist).replace("\\", "/")
            rp = f"{remote_dist}/{rel}"
            client.exec_command(f"mkdir -p {os.path.dirname(rp)}")
            sftp.put(lp, rp)
    print("uploaded admin-ui/dist")
    sftp.close()

    script = """#!/bin/bash
set -e
cd /opt/silent-vpn/backend
for f in app/services/vk_calls_auth.py app/services/vk_agent_auth.py app/api/admin.py app/config.py app/services/subscription_service.py app/api/vk_auth.py app/services/vk_id_service.py ai/vk_manager.py app/services/user_hash_service.py ai/tunnel_monitor.py; do
  docker cp "$f" backend-api-1:/app/"$f"
done
# admin-ui/dist — bind mount с хоста, docker cp не нужен
docker compose restart api
sleep 12
curl -s http://localhost:8000/api/health
echo
docker exec backend-api-1 test -f /app/app/services/vk_calls_auth.py && echo vk_calls_auth_ok
"""
    sftp2 = client.open_sftp()
    sftp2.putfo(io.BytesIO(script.encode()), "/tmp/deploy_vk_calls.sh")
    sftp2.close()
    _, out, err = client.exec_command("bash /tmp/deploy_vk_calls.sh 2>&1", timeout=180)
    print(out.read().decode("utf-8", errors="replace"))
    err_text = err.read().decode("utf-8", errors="replace")
    if err_text.strip():
        print(err_text)
    client.close()
    print("Deploy done.")


if __name__ == "__main__":
    main()
