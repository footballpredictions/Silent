#!/bin/bash
# Certbot deploy-hook: положить свежий LE в bind-mount nginx и reload.
# Не рестартить api / wdtt, не трогать DNAT.
set -euo pipefail
LINEAGE="${RENEWED_LINEAGE:-/etc/letsencrypt/live/132-243-234-162.nip.io}"
SSL_DIR="/opt/silent-vpn/backend/ssl"
install -m 644 "$LINEAGE/fullchain.pem" "$SSL_DIR/fullchain.crt"
install -m 640 "$LINEAGE/privkey.pem" "$SSL_DIR/server.key"
docker exec backend-nginx-1 nginx -s reload
echo "TLS copied to $SSL_DIR, nginx reloaded"
