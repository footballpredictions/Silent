#!/bin/bash
# If MemTotal drops below ~14GiB, balloon re-inflated — unbind again.
set -euo pipefail
mt=$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo)
if [ "${mt:-0}" -ge 14000000 ]; then
  exit 0
fi
DRIVER=/sys/bus/virtio/drivers/virtio_balloon
[ -d "$DRIVER" ] || exit 0
shopt -s nullglob
for d in "$DRIVER"/virtio*; do
  name=$(basename "$d")
  echo "$name" > "$DRIVER/unbind" 2>/dev/null || true
done
logger -t silent-balloon "unbound balloon; MemTotal was ${mt}kB"
awk '/^MemTotal:/ { printf "MemTotal=%.1fGiB after deflate\n", $2/1024/1024 }' /proc/meminfo
