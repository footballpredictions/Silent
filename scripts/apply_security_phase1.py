"""Фаза 1 hardening: localhost-only API :8000, UFW, fail2ban. SSH password не трогаем."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, REMOTE, connect, run, upload_file  # noqa: E402
from fix_tunnel_dnat import FIX_SH  # noqa: E402

UFW_SCRIPT = r"""#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "=== UFW ==="
if ! command -v ufw >/dev/null; then
  apt-get update -qq
  apt-get install -y -qq ufw
fi

# idempotent rules
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP redirect'
ufw allow 443/tcp comment 'HTTPS API'
ufw allow 56000/udp comment 'WDTT'
ufw allow 56001/udp comment 'WireGuard'
ufw allow 8443/tcp comment 'Silent Telegram MTProto'
ufw --force enable
ufw status verbose

echo "=== fail2ban ==="
if ! command -v fail2ban-client >/dev/null; then
  apt-get install -y -qq fail2ban
fi
install -d -m 0755 /etc/fail2ban/jail.d
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
port = ssh
maxretry = 5
findtime = 10m
bantime = 1h
EOF
systemctl enable fail2ban
systemctl restart fail2ban
fail2ban-client status sshd 2>/dev/null | head -5 || true
"""


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    print("Connected\n")

    print("=== 1) docker-compose.yml (127.0.0.1:8000) ===")
    upload_file(sftp, client, "docker-compose.yml")

    print("\n=== 2) Recreate api container (bind 127.0.0.1 only) ===")
    run(
        client,
        f"cd {REMOTE} && docker compose up -d api 2>&1",
        timeout=300,
    )
    run(client, "sleep 6")

    print("\n=== 2b) Reload api (app/ai are host volumes; image overlay not used) ===")
    run(client, "docker exec backend-api-1 pip install -q httpx paramiko 2>/dev/null || true")
    run(client, f"cd {REMOTE} && docker compose restart api 2>&1", timeout=120)
    run(client, "sleep 12")
    run(client, f"cd {REMOTE} && docker compose ps api 2>&1")

    print("\n=== 3) Tunnel DNAT fix (bash, not python on VPS) ===")
    sftp.putfo(io.BytesIO(FIX_SH.encode()), "/tmp/fix_tunnel_dnat.sh")
    run(client, "bash /tmp/fix_tunnel_dnat.sh 2>&1", timeout=60)

    print("\n=== 4) Health checks ===")
    run(client, "ss -tlnp | grep 8000 || true")
    run(client, "curl -sf http://127.0.0.1:8000/api/health && echo ' localhost:8000 OK'")
    run(client, "curl -skf https://127.0.0.1/api/health && echo ' nginx:443 OK'")
    run(client, "curl -sf --connect-timeout 5 http://10.66.66.1:8000/api/health && echo ' tunnel OK' || echo ' tunnel check skipped/fail'")
    run(client, "systemctl is-active wdtt && echo ' wdtt OK'")

    print("\n=== 5) UFW + fail2ban ===")
    sftp.putfo(io.BytesIO(UFW_SCRIPT.encode()), "/tmp/apply_ufw.sh")
    sftp.chmod("/tmp/apply_ufw.sh", 0o755)
    run(client, "bash /tmp/apply_ufw.sh 2>&1", timeout=300)

    print("\n=== 6) Post-UFW checks ===")
    run(client, "curl -sf http://127.0.0.1:8000/api/health && echo ' API still OK'")
    run(client, "curl -skf https://127.0.0.1/api/health && echo ' HTTPS still OK'")

    sftp.close()
    client.close()
    print("\nPhase 1 applied successfully.")


if __name__ == "__main__":
    main()
