#!/bin/bash
# Regenerate TLS certificate (run on IP change)
set -e
SERVER_IP=${1:-$(curl -s https://api.ipify.org)}
mkdir -p ../ssl
openssl req -x509 -newkey rsa:4096 \
    -keyout ../ssl/server.key \
    -out ../ssl/server.crt \
    -days 3650 -nodes \
    -subj "/CN=$SERVER_IP" \
    -addext "subjectAltName=IP:$SERVER_IP"
chmod 600 ../ssl/server.key
echo "Certificate generated for IP: $SERVER_IP"
