#!/bin/bash
# Unbind virtio balloon so the guest keeps full RAM (KVM often inflates balloon → MemTotal ~10G on a 16G VPS).
set -euo pipefail
DRIVER=/sys/bus/virtio/drivers/virtio_balloon
if [ ! -d "$DRIVER" ]; then
  exit 0
fi
shopt -s nullglob
for d in "$DRIVER"/virtio*; do
  name=$(basename "$d")
  echo "$name" > "$DRIVER/unbind" 2>/dev/null || true
done
awk '/^MemTotal:/ { printf "MemTotal=%.1fGiB\n", $2/1024/1024 }' /proc/meminfo
