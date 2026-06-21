"""Проверка wdtt / WG / iptables на VPS."""
from _deploy_common import connect, run

c = connect()
cmds = [
    "ss -ulnp | grep -E '56000|56001' || netstat -ulnp 2>/dev/null | grep 560",
    "ps aux | grep -E '[w]dtt|[W]DTT' | head -10",
    "docker ps --format '{{.Names}} {{.Status}}' | grep -i wdtt || true",
    "wg show all 2>/dev/null | head -20 || echo no-wg-show",
    "docker exec backend-api-1 printenv WG_SERVER_PUBLIC_KEY 2>/dev/null | head -c 44; echo",
    "grep -E 'WG_SERVER|VPN_SERVER|WDTT' /opt/silent-vpn/backend/.env 2>/dev/null | sed 's/PASSWORD=.*/PASSWORD=***/'",
    "iptables -t nat -L PREROUTING -n 2>/dev/null | head -15",
    "iptables -t nat -L POSTROUTING -n 2>/dev/null | grep 10.66 | head -5",
    "curl -sf http://127.0.0.1:8000/health; echo",
    "curl -sf --connect-timeout 2 http://10.66.66.1:8000/health 2>&1 || echo tunnel-fail",
]
for cmd in cmds:
    print("\n===", cmd[:70], "===")
    print(run(c, cmd)[:2000])
