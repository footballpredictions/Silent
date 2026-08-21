"""Диагностика VPS, первичная установка, статус сервисов.

Использование:
  python scripts/deploy_helper.py check
  python scripts/deploy_helper.py install
  python scripts/deploy_helper.py status
  python scripts/deploy_helper.py creds
"""
from __future__ import annotations

import sys

from _deploy_common import connect, run

GITHUB_REPO = "https://github.com/footballpredictions/Silent.git"


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    client = connect()
    print("Connected!")

    if action == "check":
        run(client, "uname -a")
        run(client, "cat /etc/os-release | grep PRETTY_NAME")
        run(client, "free -h")
        run(client, "df -h /")
        run(client, "docker --version 2>/dev/null || echo 'docker not installed'")
        run(client, "systemctl is-active docker 2>/dev/null || echo 'docker inactive'")

    elif action == "install":
        install_script = f"""
set -e
export DEBIAN_FRONTEND=noninteractive

echo "=== Installing Docker ==="
apt-get update -qq
apt-get install -y -qq curl wget git openssl ca-certificates gnupg
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker
if ! docker compose version &>/dev/null; then
    apt-get install -y -qq docker-compose-plugin
fi

echo "=== Cloning Silent VPN backend (main) ==="
mkdir -p /opt/silent-vpn
if [ -d /opt/silent-vpn/backend/.git ]; then
    cd /opt/silent-vpn/backend && git pull origin main
else
    rm -rf /opt/silent-vpn/backend
    git clone -b main {GITHUB_REPO} /opt/silent-vpn/backend
fi
cd /opt/silent-vpn/backend

echo "=== TLS certificate ==="
SERVER_IP=132.243.234.162
mkdir -p ssl
openssl req -x509 -newkey rsa:4096 \\
    -keyout ssl/server.key \\
    -out ssl/server.crt \\
    -days 3650 -nodes \\
    -subj "/CN=$SERVER_IP" \\
    -addext "subjectAltName=IP:$SERVER_IP" 2>/dev/null
chmod 600 ssl/server.key

echo "=== .env ==="
if [ ! -f .env ]; then
    SECRET_KEY=$(openssl rand -hex 32)
    JWT_SECRET=$(openssl rand -hex 32)
    POSTGRES_PASS=$(openssl rand -base64 16 | tr -d '=/+' | head -c 20)
    REDIS_PASS=$(openssl rand -base64 16 | tr -d '=/+' | head -c 20)
    WDTT_PASS=$(openssl rand -base64 16 | tr -d '=/+' | head -c 20)
    ADMIN_PASS=$(openssl rand -base64 12 | tr -d '=/+' | head -c 16)
    cat > .env <<ENVEOF
DEBUG=false
SECRET_KEY=${{SECRET_KEY}}
JWT_SECRET=${{JWT_SECRET}}
APP_NAME=Silent VPN
POSTGRES_PASSWORD=${{POSTGRES_PASS}}
REDIS_PASSWORD=${{REDIS_PASS}}
ADMIN_LOGIN=admin
ADMIN_PASSWORD=${{ADMIN_PASS}}
VPN_SERVER_IP=132.243.234.162
VPN_SERVER_PORT=56000
WDTT_MASTER_PASSWORD=${{WDTT_PASS}}
WDTT_PORT=56000
WDTT_WG_PORT=56001
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
EMAIL_FROM=noreply@silent-vpn.ru
EMAIL_FROM_NAME=Silent VPN
YUMONEY_WALLET_1=
YUMONEY_WALLET_2=
YUMONEY_SECRET=
PRICE_MONTHLY=199.0
PRICE_TWO_MONTHS=359.0
PRICE_QUARTERLY=478.0
PRICE_YEARLY=1499.0
ENVEOF
    echo "ADMIN_PASSWORD=${{ADMIN_PASS}}" > /root/silent_credentials.txt
    echo "WDTT_PASSWORD=${{WDTT_PASS}}" >> /root/silent_credentials.txt
else
    echo ".env already exists"
fi

echo "=== wdtt-server binary ==="
mkdir -p wdtt
if [ ! -f wdtt/wdtt-server ]; then
    WDTT_URL="https://github.com/amurcanov/proxy-turn-vk-android/releases/latest/download/wdtt-server-linux-amd64"
    curl -fsSL "$WDTT_URL" -o wdtt/wdtt-server || touch wdtt/wdtt-server
    chmod +x wdtt/wdtt-server 2>/dev/null || true
fi

ufw allow 22/tcp 2>/dev/null || true
ufw allow 80/tcp 2>/dev/null || true
ufw allow 443/tcp 2>/dev/null || true
ufw allow 56000/udp 2>/dev/null || true
ufw allow 56001/udp 2>/dev/null || true
echo "y" | ufw enable 2>/dev/null || true
echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-silent.conf
sysctl -p /etc/sysctl.d/99-silent.conf 2>/dev/null

mkdir -p static update/pc update/android
docker compose up -d --build
echo "=== Done ==="
"""
        stdin, stdout, stderr = client.exec_command("bash -s", timeout=600, get_pty=True)
        stdin.write(install_script)
        stdin.channel.shutdown_write()
        while True:
            line = stdout.readline()
            if not line:
                break
            print(line, end="", flush=True)

    elif action == "status":
        run(client, "cd /opt/silent-vpn/backend && docker compose ps")
        run(client, "cd /opt/silent-vpn/backend && docker compose logs --tail=20 api")

    elif action == "creds":
        run(client, "cat /root/silent_credentials.txt 2>/dev/null || echo 'no creds file'")
        run(client, "cd /opt/silent-vpn/backend && grep ADMIN_PASSWORD .env 2>/dev/null || true")

    else:
        print(f"Unknown action: {action}")
        sys.exit(1)

    client.close()


if __name__ == "__main__":
    main()
