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
# 2.2.x: auto-update тянет CDN DC 203 из getProxyConfig (иначе медиа крутится/рвётся)
MTG_VERSION = os.environ.get("MTG_VERSION", "2.2.8")
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
if [ ! -x "$BIN" ] || ! "$BIN" -v 2>/dev/null | grep -q "${{MTG_VERSION}}"; then
  rm -rf "/tmp/${{DIR}}" "/tmp/${{ASSET}}"
  curl -fsSL -o "/tmp/${{ASSET}}" "$URL"
  tar -xzf "/tmp/${{ASSET}}" -C /tmp
  # tarball layout: mtg binary may be at /tmp/mtg or /tmp/$DIR/mtg
  if [ -x "/tmp/${{DIR}}/mtg" ]; then
    install -m 755 "/tmp/${{DIR}}/mtg" "$BIN"
  else
    NEW=$(find /tmp -maxdepth 2 -type f -name mtg | head -1)
    install -m 755 "$NEW" "$BIN"
  fi
  rm -rf "/tmp/${{DIR}}" "/tmp/${{ASSET}}"
fi
"$BIN" -v || true

# Secret (reuse if present)
SECRET_FILE="$INSTALL_DIR/secret"
if [ ! -f "$SECRET_FILE" ] || [ ! -s "$SECRET_FILE" ]; then
  "$BIN" generate-secret --hex "$TLS_DOMAIN" > "$SECRET_FILE"
fi
SECRET=$(tr -d '\\n\\r ' < "$SECRET_FILE")
chmod 600 "$SECRET_FILE"

# FakeTLS ломается, если часы VPS отстают больше чем на ~3–5с (incorrect timestamp).
# Подтягиваем время по HTTP Date (NTP на этом VPS часто не синхронизируется).
REF=$(curl -sI --max-time 5 https://1.1.1.1 | awk -F': ' 'tolower($1)=="date"{{print $2}}' | tr -d '\\r')
if [ -n "$REF" ]; then date -u -s "$REF" || true; fi

# config.toml: only-ipv4 + допуск перекоса часов, DoH via dns=
# auto-update=true → CDN DC 203 из getProxyConfig (91.105.192.x:443)
# allow-fallback=false → иначе fallback на DC 3/5 и скачивание крутится без прогресса
cat > /opt/silent-tg-proxy/config.toml << CFGEOF
secret = "$SECRET"
bind-to = "0.0.0.0:$PORT"
prefer-ip = "only-ipv4"
tolerate-time-skewness = "10m"
concurrency = 8192
auto-update = true
allow-fallback-on-unknown-dc = false

[network]
dns = "https://1.1.1.1"

[network.timeout]
tcp = "15s"
http = "15s"
idle = "5m"

[defense.blocklist]
enabled = false
CFGEOF

# systemd
# VPS без рабочего IPv6: mtg default prefer-ipv6 → FakeTLS fronting падает.
# Клиенты с 10.66.x.x: blocklist firehol_level1 включает RFC1918 — держим disabled.
cat > /etc/systemd/system/silent-tg-proxy.service << SVCEOF
[Unit]
Description=Silent VPN Telegram MTProto proxy (mtg)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$BIN run /opt/silent-tg-proxy/config.toml
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

# Клиенты с AllowedIPs=0.0.0.0/0 ходят на proxy ЧЕРЕЗ туннель (WG endpoint=127.0.0.1).
# В теме — tunnel gateway 10.66.66.1 (как API). Адрес должен быть РЕАЛЬНЫМ на lo
# (REDIRECT на wdtt0 ломается: primary=10.66.0.0).
TUNNEL_GW=10.66.66.1
mkdir -p /etc/silent-vpn
cat > /etc/silent-vpn/tg-proxy-dnat.sh << 'DNAEOF'
#!/bin/bash
PORT=8443
TUNNEL_GW=10.66.66.1
ip addr add $TUNNEL_GW/32 dev lo 2>/dev/null || true
while iptables -t nat -D PREROUTING -d $TUNNEL_GW/32 -p tcp --dport $PORT -m comment --comment SILENT_TG_PROXY -j REDIRECT --to-ports $PORT 2>/dev/null; do :; done
while iptables -t nat -D OUTPUT -d $TUNNEL_GW/32 -p tcp --dport $PORT -m comment --comment SILENT_TG_PROXY -j REDIRECT --to-ports $PORT 2>/dev/null; do :; done
DNAEOF
chmod +x /etc/silent-vpn/tg-proxy-dnat.sh
/etc/silent-vpn/tg-proxy-dnat.sh
cat > /etc/systemd/system/silent-tg-proxy-dnat.service << 'DNATSVCEOF'
[Unit]
Description=Silent VPN Telegram proxy: ensure 10.66.66.1/32 on lo
After=network-online.target silent-tg-proxy.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/etc/silent-vpn/tg-proxy-dnat.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
DNATSVCEOF
systemctl daemon-reload
systemctl enable --now silent-tg-proxy-dnat.service

# Links — в теме всегда tunnel GW (VPN ON обязателен)
TG_LINK="tg://proxy?server=${{TUNNEL_GW}}&port=${{PORT}}&secret=${{SECRET}}"
HTTPS_LINK="https://t.me/proxy?server=${{TUNNEL_GW}}&port=${{PORT}}&secret=${{SECRET}}"
PUBLIC_HTTPS="https://t.me/proxy?server=${{HOST}}&port=${{PORT}}&secret=${{SECRET}}"
cat > /root/silent_tg_proxy.txt << EOF
# Silent Telegram MTProto proxy
# Primary server = tunnel gateway (VPN must be ON)
server=$TUNNEL_GW
port=$PORT
secret=$SECRET
tls_domain=$TLS_DOMAIN

$HTTPS_LINK

$TG_LINK

# Public fallback (direct, no VPN):
$PUBLIC_HTTPS
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
    tg_link = ""
    for line in out.splitlines():
        if line.startswith("PROXY_HTTPS_LINK="):
            https_link = line.split("=", 1)[1].strip()
        elif line.startswith("PROXY_TG_LINK="):
            tg_link = line.split("=", 1)[1].strip()
    # В тему — tg:// чтобы клиенты открывали установленный Telegram, не сайт скачивания
    theme_link = tg_link or https_link
    if not theme_link:
        client.close()
        raise SystemExit("Не удалось получить PROXY_TG_LINK / PROXY_HTTPS_LINK")

    # Merge into theme via psql (asyncpg-only container has no psycopg2)
    patch_sh = f"""#!/bin/bash
set -euo pipefail
docker exec backend-db-1 psql -U silent -d silent_vpn -t -A -c "SELECT value FROM app_settings WHERE key='theme';" > /tmp/theme_raw.json
python3 - <<'PY'
import json
link = {json.dumps(theme_link)}
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
    print("Ссылка в теме (tg://):")
    print(theme_link)
    if https_link:
        print("HTTPS (для браузера):")
        print(https_link)


if __name__ == "__main__":
    main()
