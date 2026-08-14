"""Диагностика и тюнинг egress Соты 1 (Telemost). Без рестарта живых olcrtc2-сессий.

  cd backend
  python scripts/tune_olcrtc2_cell_net.py
  python scripts/tune_olcrtc2_cell_net.py 87.58.213.193
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, run  # noqa: E402

QUEEN_IP = "132.243.234.162"
DEFAULT_CELL = "87.58.213.193"

CREDS_PY = r"""
import asyncio, json, sys
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.hive_cell import HiveCell
from app.services.hive_service import resolve_ssh_password

async def main():
    want = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    out = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(HiveCell).where(HiveCell.is_queen == False))).scalars().all()
        for r in rows:
            if want and r.public_ip != want:
                continue
            pwd = resolve_ssh_password(r)
            out.append({"ip": r.public_ip, "name": r.name, "pwd": pwd or ""})
    print(json.dumps(out))
asyncio.run(main())
"""

CHECK_SH = r"""
set +e
echo "======== HOST ========"
hostname; uname -a
echo "public: $(curl -4 -s --max-time 5 ifconfig.me || echo '?')"
nproc; lscpu | grep -E 'Model name|CPU\(s\)|Thread|MHz' | head -8
echo
echo "======== LOAD / MEM / DISK ========"
uptime
free -h
df -h / | tail -1
echo
echo "======== CPU now (1s) ========"
top -bn1 | head -12
echo
echo "======== SYSCTL NOW ========"
sysctl -n net.ipv4.ip_forward net.ipv4.tcp_congestion_control net.core.default_qdisc \
  net.ipv4.tcp_slow_start_after_idle net.ipv4.tcp_mtu_probing net.core.rmem_max \
  net.core.wmem_max net.core.netdev_max_backlog net.ipv4.ip_local_port_range \
  net.ipv4.conf.all.rp_filter 2>/dev/null
echo "sysctl.d:"; ls /etc/sysctl.d/ 2>/dev/null
echo
echo "======== IFACE / QDISC ========"
ETH=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
echo "ETH=$ETH"
ip -4 addr show dev "$ETH" 2>/dev/null | head -6
ip link show "$ETH" 2>/dev/null | head -2
tc qdisc show dev "$ETH" 2>/dev/null
ethtool -k "$ETH" 2>/dev/null | grep -E 'tcp-segmentation|generic-segmentation|rx-checksum|tx-checksum' | head -8
echo
echo "======== IPTABLES ========"
iptables -S FORWARD 2>/dev/null | head -20
echo "--- NAT POSTROUTING ---"
iptables -t nat -S POSTROUTING 2>/dev/null | head -20
echo "--- NAT PREROUTING ---"
iptables -t nat -S PREROUTING 2>/dev/null | head -15
echo
echo "======== WG / WDTT ========"
systemctl is-active wdtt silent-cell-agent 2>/dev/null
wg show 2>/dev/null | head -25
echo
echo "======== OLCRTC2 UNITS ========"
systemctl cat olcrtc2@.service 2>/dev/null | head -30
echo "--- running ---"
systemctl list-units 'olcrtc2@*' --no-pager --no-legend 2>/dev/null
echo "--- cgroup ---"
for s in $(systemctl list-units --type=service --state=running --no-legend 'olcrtc2@*' | awk '{print $1}'); do
  echo "-- $s --"
  systemctl show "$s" -p CPUQuotaPerSecUSec -p MemoryMax -p MemoryCurrent -p CPUAccounting --no-pager
  cat /sys/fs/cgroup/system.slice/${s}/cpu.stat 2>/dev/null | head -8
  cat /sys/fs/cgroup/system.slice/${s}/cpu.max 2>/dev/null
done
echo
echo "======== DNS ========"
cat /etc/resolv.conf 2>/dev/null | head -8
echo
echo "======== EGRESS TCP ========"
for h in www.youtube.com www.gstatic.com ya.ru turn.tel.yandex.net 1.1.1.1 8.8.8.8; do
  start=$(date +%s%3N)
  if timeout 3 bash -c "echo >/dev/tcp/${h}/443" 2>/dev/null || timeout 3 bash -c "echo >/dev/tcp/${h}/80" 2>/dev/null; then
    end=$(date +%s%3N)
    echo "OK  $h $((end-start))ms"
  else
    echo "FAIL $h"
  fi
done
echo
echo "======== CURL TTFB ========"
for url in \
  "https://www.youtube.com/" \
  "https://www.gstatic.com/generate_204" \
  "https://ya.ru/" \
  "https://cloudflare.com/cdn-cgi/trace"
do
  out=$(curl -4 -s -o /dev/null -w "%{http_code} ttfb=%{time_starttransfer}s total=%{time_total}s" \
    --connect-timeout 5 --max-time 10 "$url" 2>/dev/null || echo ERR)
  echo "$url -> $out"
done
echo
echo "======== 20MB DOWNLOAD (cloudflare) ========"
curl -4 -s -o /dev/null -w "cf20mb code=%{http_code} speed=%{speed_download}B/s total=%{time_total}s\n" \
  --connect-timeout 8 --max-time 25 \
  "https://speed.cloudflare.com/__down?bytes=20000000" || echo "cf download ERR"
echo
echo "======== 10MB yandex ========"
curl -4 -s -o /dev/null -w "ya code=%{http_code} speed=%{speed_download}B/s total=%{time_total}s\n" \
  --connect-timeout 8 --max-time 20 \
  "https://yandex.ru/favicon.ico" || echo "ya ERR"
"""

APPLY_SH = r"""
set -e
ETH=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1); exit}')
echo "ETH=$ETH"

# BBR if kernel allows
modprobe tcp_bbr 2>/dev/null || true
if grep -q bbr /proc/sys/net/ipv4/tcp_available_congestion_control 2>/dev/null; then
  sysctl -w net.ipv4.tcp_congestion_control=bbr
  sysctl -w net.core.default_qdisc=fq
else
  echo "WARN: BBR not available, keep $(sysctl -n net.ipv4.tcp_congestion_control)"
fi

cat > /etc/sysctl.d/99-silent-olcrtc.conf << 'EOF'
net.ipv4.ip_forward=1
net.ipv4.conf.all.forwarding=1
net.ipv4.conf.default.forwarding=1
net.ipv4.conf.all.rp_filter=2
net.ipv4.conf.default.rp_filter=2
net.ipv4.tcp_slow_start_after_idle=0
net.ipv4.tcp_mtu_probing=1
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_notsent_lowat=16384
net.ipv4.tcp_keepalive_time=60
net.ipv4.tcp_keepalive_intvl=10
net.ipv4.tcp_keepalive_probes=6
net.ipv4.ip_local_port_range=1024 65535
net.ipv4.tcp_tw_reuse=1
net.core.somaxconn=4096
net.core.netdev_max_backlog=16384
net.core.rmem_max=33554432
net.core.wmem_max=33554432
net.core.rmem_default=262144
net.core.wmem_default=262144
net.ipv4.tcp_rmem=4096 262144 33554432
net.ipv4.tcp_wmem=4096 262144 33554432
net.ipv4.udp_rmem_min=8192
net.ipv4.udp_wmem_min=8192
net.core.optmem_max=65536
EOF
# congestion in same file only if bbr loaded
if grep -q bbr /proc/sys/net/ipv4/tcp_available_congestion_control 2>/dev/null; then
  echo "net.core.default_qdisc=fq" >> /etc/sysctl.d/99-silent-olcrtc.conf
  echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.d/99-silent-olcrtc.conf
fi
sysctl -p /etc/sysctl.d/99-silent-olcrtc.conf

# conntrack if present
if [ -e /proc/sys/net/netfilter/nf_conntrack_max ]; then
  sysctl -w net.netfilter.nf_conntrack_max=262144 || true
  echo "net.netfilter.nf_conntrack_max=262144" >> /etc/sysctl.d/99-silent-olcrtc.conf
fi

if [ -n "$ETH" ]; then
  ip link set dev "$ETH" txqueuelen 10000 2>/dev/null || true
  tc qdisc replace dev "$ETH" root fq 2>/dev/null || true
  # MASQUERADE for WG clients if missing
  iptables -t nat -C POSTROUTING -s 10.66.66.0/24 -o "$ETH" -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s 10.66.66.0/24 -o "$ETH" -j MASQUERADE
  iptables -C FORWARD -s 10.66.66.0/24 -j ACCEPT 2>/dev/null || \
    iptables -I FORWARD 1 -s 10.66.66.0/24 -j ACCEPT
  iptables -C FORWARD -d 10.66.66.0/24 -j ACCEPT 2>/dev/null || \
    iptables -I FORWARD 1 -d 10.66.66.0/24 -j ACCEPT
  iptables -P FORWARD ACCEPT 2>/dev/null || true
fi

# olcrtc2@ template: no CPUQuota, 1G RAM — daemon-reload only, no restart
mkdir -p /opt/silent-vpn/olcrtc2
cat > /etc/systemd/system/olcrtc2@.service << 'EOF'
[Unit]
Description=Silent VPN olcrtc2-srv %i
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/silent-vpn/olcrtc2
EnvironmentFile=-/opt/silent-vpn/olcrtc2/env.d/%i.env
ExecStart=/opt/silent-vpn/olcrtc2/olcrtc2-srv
Restart=on-failure
RestartSec=5
MemoryMax=1G
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

# Live cgroup bump without killing sessions
for s in $(systemctl list-units --type=service --state=running --no-legend 'olcrtc2@*' | awk '{print $1}'); do
  echo "set-property $s CPUQuota= MemoryMax=1G"
  systemctl set-property "$s" CPUQuota= MemoryMax=1G --runtime || true
done

echo "======== AFTER SYSCTL ========"
sysctl -n net.ipv4.ip_forward net.ipv4.tcp_congestion_control net.core.default_qdisc \
  net.ipv4.tcp_slow_start_after_idle net.core.rmem_max
echo "qdisc:"; tc qdisc show dev "$ETH" 2>/dev/null
echo "units CPUQuota after:"
for s in $(systemctl list-units --type=service --state=running --no-legend 'olcrtc2@*' | awk '{print $1}'); do
  systemctl show "$s" -p Id -p CPUQuotaPerSecUSec -p MemoryMax --no-pager
  cat /sys/fs/cgroup/system.slice/${s}/cpu.max 2>/dev/null
done

echo "======== AFTER 20MB DOWNLOAD ========"
curl -4 -s -o /dev/null -w "cf20mb code=%{http_code} speed=%{speed_download}B/s total=%{time_total}s\n" \
  --connect-timeout 8 --max-time 25 \
  "https://speed.cloudflare.com/__down?bytes=20000000" || echo "cf download ERR"
echo "TUNE_OK"
"""


def _api_container(queen) -> str:
    names = run(queen, "docker ps --format '{{.Names}}'")
    for line in names.splitlines():
        n = line.strip().strip("'")
        if n == "backend-api-1" or (n.endswith("-api-1") and "backend" in n):
            return n
    for line in names.splitlines():
        n = line.strip().strip("'")
        if "api" in n.lower():
            return n
    raise SystemExit(f"api container not found in: {names!r}")


def _cell_ssh(cell_ip: str) -> paramiko.SSHClient:
    queen = connect()
    api = _api_container(queen)
    sftp = queen.open_sftp()
    with sftp.file("/tmp/olcrtc2_tune_creds.py", "w") as f:
        f.write(CREDS_PY)
    sftp.close()
    run(queen, f"docker cp /tmp/olcrtc2_tune_creds.py {api}:/tmp/olcrtc2_tune_creds.py")
    raw = run(
        queen,
        f"docker exec -w /app -e PYTHONPATH=/app {api} python /tmp/olcrtc2_tune_creds.py {cell_ip}",
    )
    queen.close()
    rows = json.loads(raw.strip().splitlines()[-1])
    if not rows:
        raise SystemExit(f"no hive_cell for {cell_ip}")
    pwd = (rows[0].get("pwd") or "").strip()
    name = rows[0].get("name") or cell_ip
    if not pwd:
        raise SystemExit(f"no SSH password for {cell_ip}")
    print(f"=== cell {name} {cell_ip} ===")
    cell = paramiko.SSHClient()
    cell.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cell.connect(cell_ip, username="root", password=pwd, timeout=25)
    return cell


def _exec(cell: paramiko.SSHClient, script: str, timeout: int = 180) -> str:
    _, stdout, stderr = cell.exec_command(script, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        out += "\n--- stderr ---\n" + err[:2000]
    return out


VERIFY_SH = r"""
set +e
echo "agent: $(systemctl is-active silent-cell-agent)"
ss -lntp | grep ':9100' || true
journalctl -u silent-cell-agent -n 12 --no-pager
echo "--- quotas ---"
for s in $(systemctl list-units --type=service --state=running --no-legend 'olcrtc2@*' | awk '{print $1}'); do
  echo "$s"
  systemctl show "$s" -p CPUQuotaPerSecUSec -p MemoryMax --no-pager
  echo -n "cpu.max="; cat /sys/fs/cgroup/system.slice/${s}/cpu.max 2>/dev/null; echo
done
echo "--- template ---"
grep -E 'CPUQuota|MemoryMax' /etc/systemd/system/olcrtc2@.service || echo "no CPUQuota in template (good)"
echo "--- sysctl ---"
sysctl -n net.ipv4.tcp_congestion_control net.core.default_qdisc net.ipv4.tcp_slow_start_after_idle net.ipv4.ip_forward
echo "--- load ---"
uptime
vmstat 1 3
"""


def main() -> None:
    args = [a for a in sys.argv[1:] if a]
    verify_only = "--verify" in args
    args = [a for a in args if a != "--verify"]
    cell_ip = (args[0] if args else DEFAULT_CELL).strip()
    if cell_ip == QUEEN_IP:
        raise SystemExit("REFUSE: do not tune WDTT queen as olcrtc exit")
    cell = _cell_ssh(cell_ip)
    try:
        if verify_only:
            print("######## VERIFY ########")
            print(_exec(cell, VERIFY_SH, timeout=40))
            return
        print("######## BEFORE ########")
        print(_exec(cell, CHECK_SH, timeout=120))
        print("######## APPLY (no session restart) ########")
        print(_exec(cell, APPLY_SH, timeout=120))
    finally:
        cell.close()


if __name__ == "__main__":
    main()
