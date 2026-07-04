"""Установка cell-agent (systemd) на VPN-соту."""
from __future__ import annotations

import io
import os
import secrets
import sys

from _deploy_common import BACKEND_ROOT, connect, load_env, run

load_env()

CELL_SECRET = os.environ.get("DEPLOY_CELL_AGENT_SECRET") or secrets.token_urlsafe(32)
CELL_PORT = os.environ.get("DEPLOY_CELL_AGENT_PORT", "9100")
HIVE_URL = os.environ.get("DEPLOY_HIVE_API_URL", "https://132-243-234-162.nip.io")
PUBLIC_IP = os.environ.get("DEPLOY_CELL_PUBLIC_IP", "")
WG_PUBKEY = os.environ.get("DEPLOY_WG_SERVER_PUBLIC_KEY", "")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: DEPLOY_PASS=... python scripts/deploy_cell_agent.py <cell_vps_ip>")
        print("Optional: DEPLOY_CELL_AGENT_SECRET, DEPLOY_CELL_PUBLIC_IP, DEPLOY_WG_SERVER_PUBLIC_KEY")
        raise SystemExit(1)
    cell_host = sys.argv[1]
    os.environ["DEPLOY_HOST"] = cell_host
    client = connect()

    agent_main = (BACKEND_ROOT / "cell-agent" / "main.py").read_text(encoding="utf-8")
    agent_req = (BACKEND_ROOT / "cell-agent" / "requirements.txt").read_text(encoding="utf-8")

    sftp = client.open_sftp()
    client.exec_command("mkdir -p /opt/silent-vpn/cell-agent")
    sftp.putfo(io.BytesIO(agent_main.encode()), "/opt/silent-vpn/cell-agent/main.py")
    sftp.putfo(io.BytesIO(agent_req.encode()), "/opt/silent-vpn/cell-agent/requirements.txt")

    script = f"""#!/bin/bash
set -e
python3 -m venv /opt/silent-vpn/cell-agent/venv
/opt/silent-vpn/cell-agent/venv/bin/pip install -q -r /opt/silent-vpn/cell-agent/requirements.txt
cat > /etc/systemd/system/silent-cell-agent.service << SVCEOF
[Unit]
Description=Silent VPN Cell Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/silent-vpn/cell-agent
Environment=CELL_AGENT_SECRET={CELL_SECRET}
Environment=CELL_PUBLIC_IP={PUBLIC_IP or cell_host}
Environment=WG_SERVER_PUBLIC_KEY={WG_PUBKEY}
Environment=HIVE_API_URL={HIVE_URL}
Environment=CELL_LINK_CAPACITY_MBPS=1000
Environment=TUNNEL_API_URL=http://10.66.66.1:8000
ExecStart=/opt/silent-vpn/cell-agent/venv/bin/uvicorn main:app --host 0.0.0.0 --port {CELL_PORT}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF
ufw allow {CELL_PORT}/tcp 2>/dev/null || true
systemctl daemon-reload
systemctl enable silent-cell-agent
systemctl restart silent-cell-agent
sleep 2
systemctl status silent-cell-agent --no-pager | head -12
curl -s http://127.0.0.1:{CELL_PORT}/health || true
"""
    sftp.putfo(io.BytesIO(script.encode()), "/tmp/deploy_cell_agent.sh")
    sftp.close()
    run(client, "bash /tmp/deploy_cell_agent.sh 2>&1", timeout=180)
    client.close()
    print("Done")
    print(f"CELL_AGENT_SECRET (введите в админке Улей): {CELL_SECRET}")
    print(f"API URL для админки: http://{cell_host}:{CELL_PORT}")


if __name__ == "__main__":
    main()
