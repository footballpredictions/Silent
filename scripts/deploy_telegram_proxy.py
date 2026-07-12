"""MTProto proxy (mtg) на VPS для ускорения Telegram поверх Silent VPN.

Устанавливает systemd-сервис silent-tg-proxy, открывает порт в UFW,
пишет ссылку в /root/silent_tg_proxy.txt и прописывает её в theme (app_settings).

Запуск:
  cd backend
  python scripts/deploy_telegram_proxy.py
"""
from __future__ import annotations

import io
import json
import os
import sys

from _deploy_common import connect, load_env, run

load_env()

HOST = os.environ.get("DEPLOY_HOST", "132.243.234.162")
PORT = int(os.environ.get("TELEGRAM_PROXY_PORT", "8443"))
# Fake-TLS домен для ee-secret (DPI)
TLS_DOMAIN = os.environ.get("TELEGRAM_PROXY_TLS_DOMAIN", "cloudflare.com")
MTG_VERSION = os.environ.get("MTG_VERSION", "2.1.7")
CONTAINER = os.environ.get("DEPLOY_CONTAINER", "backend-api-1")


def main() -> None:
    client = connect()
    script = f"""
set -euo pipefail
PORT={PORT}
HOST={HOST}
TLS_DOMAIN={TLS_DOMAIN}
MTG_VERSION={MTG_VERSION}
INSTALL_DIR=/opt/silent-tg-proxy
BIN=/usr/local/bin/mtg

mkdir -p "$INSTALL_DIR"
cd /tmp

# Binary
ARCH=amd64
DIR="mtg-${{MTG_VERSION}}-linux-${{ARCH}}"
ASSET="${{DIR}}.tar.gz"
URL="https://github.com/9seconds/mtg/releases/download/v${{MTG_VERSION}}/${{ASSET}}"
if [ ! -x "$BIN" ] || ! "$BIN" --version 2>/dev/null | grep -q "${{MTG_VERSION}}"; then
  rm -rf "/tmp/${{DIR}}" "/tmp/${{ASSET}}"
  curl -fsSL -o "/tmp/${{ASSET}}" "$URL"
  tar -xzf "/tmp/${{ASSET}}" -C /tmp
  install -m 755 "/tmp/${{DIR}}/mtg" "$BIN"
  rm -rf "/tmp/${{DIR}}" "/tmp/${{ASSET}}"
fi
"$BIN" --version || true

# Secret (reuse if present)
SECRET_FILE="$INSTALL_DIR/secret"
if [ ! -f "$SECRET_FILE" ] || [ ! -s "$SECRET_FILE" ]; then
  "$BIN" generate-secret --hex "$TLS_DOMAIN" > "$SECRET_FILE"
fi
SECRET=$(tr -d '\\n\\r ' < "$SECRET_FILE")
chmod 600 "$SECRET_FILE"

# systemd
cat > /etc/systemd/system/silent-tg-proxy.service << SVCEOF
[Unit]
Description=Silent VPN Telegram MTProto proxy (mtg)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$BIN simple-run 0.0.0.0:$PORT $SECRET
Restart=always
RestartSec=3
LimitNOFILE=65535
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable silent-tg-proxy
systemctl restart silent-tg-proxy
sleep 1
systemctl --no-pager --full status silent-tg-proxy | head -20 || true

ufw allow ${{PORT}}/tcp comment 'Silent Telegram MTProto' 2>/dev/null || true

# Links
TG_LINK="tg://proxy?server=${{HOST}}&port=${{PORT}}&secret=${{SECRET}}"
HTTPS_LINK="https://t.me/proxy?server=${{HOST}}&port=${{PORT}}&secret=${{SECRET}}"
cat > /root/silent_tg_proxy.txt << EOF
# Silent Telegram MTProto proxy
server=$HOST
port=$PORT
secret=$SECRET
tls_domain=$TLS_DOMAIN

$HTTPS_LINK

$TG_LINK
EOF
chmod 600 /root/silent_tg_proxy.txt
echo "PROXY_HTTPS_LINK=$HTTPS_LINK"
echo "PROXY_TG_LINK=$TG_LINK"
"""
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(script.encode()), "/tmp/deploy_telegram_proxy.sh")
    sftp.close()
    out = run(client, "bash /tmp/deploy_telegram_proxy.sh 2>&1", timeout=180)
    print(out)

    https_link = ""
    for line in out.splitlines():
        if line.startswith("PROXY_HTTPS_LINK="):
            https_link = line.split("=", 1)[1].strip()
            break
    if not https_link:
        client.close()
        raise SystemExit("Не удалось получить PROXY_HTTPS_LINK из вывода установки")

    # Merge into theme via psql (asyncpg-only container has no psycopg2)
    patch_sh = f"""#!/bin/bash
set -euo pipefail
LINK={json.dumps(https_link)}
LABEL='Ускорить Telegram'
docker exec backend-db-1 psql -U silent -d silent_vpn -t -A -c "SELECT value FROM app_settings WHERE key='theme';" > /tmp/theme_raw.json
python3 - <<'PY'
import json
link = {json.dumps(https_link)}
label = "Ускорить Telegram"
with open("/tmp/theme_raw.json", encoding="utf-8") as f:
    raw = f.read().strip()
data = json.loads(raw) if raw else {{}}
data["telegram_proxy_url"] = link
data["telegram_proxy_menu_label"] = label
with open("/tmp/theme_patched.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False)
print("patched ok")
PY
# dollar-quoting to avoid escaping JSON
python3 - <<'PY'
from pathlib import Path
payload = Path("/tmp/theme_patched.json").read_text(encoding="utf-8")
sql = "UPDATE app_settings SET value = $json$%s$json$, updated_at = NOW() WHERE key = 'theme';\\n" % payload
Path("/tmp/patch_theme.sql").write_text(sql, encoding="utf-8")
PY
docker cp /tmp/patch_theme.sql backend-db-1:/tmp/patch_theme.sql
docker exec backend-db-1 psql -U silent -d silent_vpn -f /tmp/patch_theme.sql
echo theme_proxy_ok
"""
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(patch_sh.encode()), "/tmp/patch_theme_tg_proxy.sh")
    sftp.close()
    patch_out = run(client, "bash /tmp/patch_theme_tg_proxy.sh 2>&1", timeout=60)
    print(patch_out)
    run(client, f"docker compose -f /opt/silent-vpn/backend/docker-compose.yml restart api 2>&1 | tail -5", timeout=60)
    client.close()
    print("Done")
    print("Ссылка (также в /root/silent_tg_proxy.txt):")
    print(https_link)


if __name__ == "__main__":
    main()
