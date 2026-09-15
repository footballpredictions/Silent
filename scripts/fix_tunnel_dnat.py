"""Починка tunnel API: 10.66.66.1:8000 → backend-api (PREROUTING + OUTPUT)."""
from __future__ import annotations

import io

from _deploy_common import connect, run

# Соты, которым Улей пускает :8000 (docker-proxy только 127.0.0.1).
# Без IP соты DNAT 10.66.66.1:8000 с клиента мёртв. Публично 8000 не открываем.
CELL_API_SOURCE_IPS = (
    "87.58.213.193",  # Сота 1
    "78.17.74.27",    # Сота 2
    "192.177.26.38",  # Сота 3 / Сервер 4 (ИИ-выход)
)

FIX_SH = r"""#!/bin/bash
set -euo pipefail

API_IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' backend-api-1 2>/dev/null || echo "")
if [ -z "$API_IP" ]; then
  echo "backend-api-1 not found" >&2
  exit 1
fi
TARGET="${API_IP}:8000"
echo "[fix] tunnel 10.66.66.1:8000 -> $TARGET"

strip_rules() {
  local chain=$1
  while true; do
    line=$(iptables -t nat -L "$chain" -n --line-numbers 2>/dev/null | grep '10.66.66.1' | grep '8000' | head -1 | awk '{print $1}' || true)
    [ -z "$line" ] && break
    iptables -t nat -D "$chain" "$line" || break
  done
}

strip_rules PREROUTING
strip_rules OUTPUT

while true; do
  line=$(iptables -t nat -L PREROUTING -n --line-numbers 2>/dev/null | grep CELL_API | head -1 | awk '{print $1}' || true)
  [ -z "$line" ] && break
  iptables -t nat -D PREROUTING "$line" || break
done

iptables -t nat -A PREROUTING -d 10.66.66.1/32 -p tcp -m tcp --dport 8000 \
  -m comment --comment "WDTT_API" -j DNAT --to-destination "$TARGET"
iptables -t nat -A OUTPUT -d 10.66.66.1/32 -p tcp -m tcp --dport 8000 \
  -m comment --comment "WDTT_API" -j DNAT --to-destination "$TARGET"

# hairpin / forward к docker bridge
iptables -C FORWARD -d "$API_IP"/32 -p tcp --dport 8000 -j ACCEPT 2>/dev/null \
  || iptables -I FORWARD 1 -d "$API_IP"/32 -p tcp --dport 8000 -j ACCEPT
iptables -C FORWARD -s "$API_IP"/32 -p tcp --sport 8000 -j ACCEPT 2>/dev/null \
  || iptables -I FORWARD 1 -s "$API_IP"/32 -p tcp --sport 8000 -j ACCEPT

# Соты DNAT 10.66.66.1:8000 на Улей:8000, а docker-proxy слушает только 127.0.0.1:8000.
# REDIRECT на :8000 с eth0 = Connection refused. Nginx :80 — allow только IP сот.
for CELL_IP in __CELL_IPS__; do
  iptables -t nat -C PREROUTING -s "$CELL_IP"/32 -p tcp --dport 8000 \
    -m comment --comment "CELL_API" -j REDIRECT --to-ports 80 2>/dev/null \
    || iptables -t nat -I PREROUTING 1 -s "$CELL_IP"/32 -p tcp --dport 8000 \
      -m comment --comment "CELL_API" -j REDIRECT --to-ports 80
done

echo "[fix] PREROUTING:"; iptables -t nat -L PREROUTING -n | grep -E '10.66|CELL_API' || true
echo "[fix] OUTPUT:"; iptables -t nat -L OUTPUT -n | grep 10.66 || true

ok=0
if curl -sf --connect-timeout 3 "http://${API_IP}:8000/health" >/dev/null; then
  echo "[fix] OK direct api $API_IP:8000"
  ok=1
fi
if curl -sf --connect-timeout 3 http://10.66.66.1:8000/health >/dev/null; then
  echo "[fix] OK tunnel http://10.66.66.1:8000/health"
  ok=1
fi
if [ "$ok" = 0 ]; then
  echo "[fix] FAIL both tunnel checks" >&2
  curl -v --connect-timeout 3 http://10.66.66.1:8000/health 2>&1 | tail -8 || true
  exit 1
fi
""".replace("__CELL_IPS__", " ".join(CELL_API_SOURCE_IPS))


def main() -> None:
    client = connect()
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(FIX_SH.encode()), "/tmp/fix_tunnel_dnat.sh")
    sftp.close()
    print(run(client, "bash /tmp/fix_tunnel_dnat.sh 2>&1", timeout=30))
    client.close()
    print("Done.")


if __name__ == "__main__":
    main()
