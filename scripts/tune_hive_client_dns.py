"""Залить sync клиентского DNS Улья (CF DNAT). wdtt не рестартит.

  cd backend
  python scripts/tune_hive_client_dns.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect  # noqa: E402
from app.services.hive_client_dns import BIN_SYNC, threat_dns_sync_script  # noqa: E402

DIAG = r"""
echo "=== wdtt ==="
systemctl is-active wdtt
echo "=== nat :53 ==="
iptables -t nat -S PREROUTING 2>/dev/null | grep -- "--dport 53" || echo "(нет)"
echo "=== hive DNS to CF ==="
dig +time=2 +tries=1 @1.1.1.1 example.com A +short 2>/dev/null | head -3 || true
echo "=== hive DNS to Yandex ==="
dig +time=2 +tries=1 @77.88.8.8 example.com A +short 2>/dev/null | head -3 || true
echo "=== wdtt udp 56000 ==="
ss -uH state unconn 2>/dev/null | wc -l
ss -uH 2>/dev/null | grep -c ':56000' || true
echo "=== wg iface peers (no keys) ==="
wg show all 2>/dev/null | awk '/^interface:/{i=$2} /^peer:/{p++} END{print "ifaces"; print "peers",p+0}'
echo "=== wdtt journal handshake/timeout (no secrets) ==="
journalctl -u wdtt -n 120 --no-pager 2>/dev/null | grep -iE 'timeout|dtls|too many|drop|udp' | tail -25 || true
"""


def _exec(client, script: str, timeout: int = 90) -> str:
    _, stdout, stderr = client.exec_command(script, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + (("\nSTDERR\n" + err) if err.strip() else "")


def main() -> None:
    queen = connect(timeout=25, attempts=3, pause=4)
    script = threat_dns_sync_script()
    sftp = queen.open_sftp()
    with sftp.file(BIN_SYNC, "w") as f:
        f.write(script)
    sftp.close()
    print("=== chmod + run sync (iptables only) ===")
    print(_exec(queen, f"chmod 755 {BIN_SYNC} ; bash {BIN_SYNC}"))
    print("=== diag ===")
    print(_exec(queen, DIAG, timeout=40))
    queen.close()


if __name__ == "__main__":
    main()
