"""Установка wdtt-server как systemd-сервис на VPS."""
from __future__ import annotations

import io
import os
import sys

from _deploy_common import connect, load_env, run

load_env()
WDTT_PASS = os.environ.get("DEPLOY_WDTT_MASTER_PASSWORD", "")
if not WDTT_PASS:
    raise SystemExit("Задайте DEPLOY_WDTT_MASTER_PASSWORD в .env.deploy (или возьмите WDTT_MASTER_PASSWORD с сервера)")


def main() -> None:
    client = connect()
    run(client, "cd /opt/silent-vpn/backend && docker compose stop wdtt 2>&1 || true", timeout=15)

    script = f"""
set -e
cp /opt/silent-vpn/backend/wdtt/wdtt-server /usr/local/bin/wdtt-server
chmod +x /usr/local/bin/wdtt-server
mkdir -p /etc/wdtt
if [ ! -f /etc/wdtt/passwords.json ]; then
cat > /etc/wdtt/passwords.json << 'PWEOF'
{{
  "master": "{WDTT_PASS}",
  "users": []
}}
PWEOF
fi
ufw allow 56000/udp 2>/dev/null || true
ufw allow 56001/udp 2>/dev/null || true
ETH=$(ip route get 8.8.8.8 | awk '{{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}}')
iptables -t nat -C POSTROUTING -s 10.66.66.0/24 -o $ETH -j MASQUERADE 2>/dev/null || \\
    iptables -t nat -A POSTROUTING -s 10.66.66.0/24 -o $ETH -j MASQUERADE
sysctl -w net.ipv4.ip_forward=1
cat > /etc/systemd/system/wdtt.service << 'SVCEOF'
[Unit]
Description=WDTT VPN Server
After=network.target

[Service]
Type=simple
ExecStartPre=-/bin/sh -c "ip link show wdtt0 >/dev/null 2>&1 && ip link del wdtt0 2>/dev/null || true"
ExecStart=/usr/local/bin/wdtt-server -listen 0.0.0.0:56000 -wg-port 56001 -config-dir /etc/wdtt -password {WDTT_PASS}
Restart=always
RestartSec=3
LimitNOFILE=65535
# RSS на проде ~3GB при малом online — мягкий/жёсткий потолок, чтобы не сожрать всю RAM Улья
MemoryHigh=4G
MemoryMax=6G

[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload
systemctl enable wdtt
systemctl restart wdtt
sleep 3
systemctl status wdtt --no-pager | head -15
"""
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(script.encode()), "/tmp/deploy_wdtt_systemd.sh")
    sftp.close()
    run(client, "bash /tmp/deploy_wdtt_systemd.sh 2>&1", timeout=90)
    client.close()
    print("Done")


if __name__ == "__main__":
    main()
