"""Снять мёртвые GETCONF extras на Улье. Ключи devices не трогаем, wdtt не рестартим.

  cd backend
  python scripts/gc_queen_stale_extras.py
"""
from __future__ import annotations

import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import CONTAINER, connect  # noqa: E402
from app.services.vpn_kick_select import parse_wg_show_dump, select_gc_extra_pubs  # noqa: E402

KNOWN_PY = r"""
import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import Device
from app.services.vpn_kick_select import merge_known_device_pubs

async def main():
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Device.wg_public_key).where(Device.is_active == True)  # noqa: E712
            )
        ).all()
        for p in sorted(merge_known_device_pubs([r[0] for r in rows])):
            print(p)

asyncio.run(main())
"""

DUMP_SH = r"""
wg show wdtt0 allowed-ips; echo ---HS---; wg show wdtt0 latest-handshakes
"""

AGES_SH = r"""
echo wdtt=$(systemctl is-active wdtt)
now=$(date +%s)
wg show wdtt0 latest-handshakes 2>/dev/null | awk -v now="$now" '
NF>=2 {
  n++
  ts=$2
  if (ts+0==0) never++
  else {
    age=now-ts
    if (age<180) live++
    else if (age<3600) h1++
    else if (age<21600) h6++
    else stale++
  }
}
END {
  print "peers", n+0, "live3m", live+0, "1h", h1+0, "6h", h6+0, "stale6h+", stale+0, "never", never+0
}'
"""


def _exec(client, script: str, timeout: int = 90) -> str:
    _, stdout, stderr = client.exec_command(script, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print("stderr:", err.strip()[:400])
    return out


def main() -> None:
    queen = connect(timeout=25, attempts=3, pause=4)
    print("=== before ===")
    print(_exec(queen, AGES_SH).strip())

    sftp = queen.open_sftp()
    with sftp.file("/tmp/known_device_pubs.py", "w") as f:
        f.write(KNOWN_PY)
    sftp.close()
    _exec(queen, f"docker cp /tmp/known_device_pubs.py {CONTAINER}:/tmp/known_device_pubs.py", timeout=20)
    known_raw = _exec(
        queen,
        f"docker exec -w /app -e PYTHONPATH=/app {CONTAINER} python /tmp/known_device_pubs.py",
        timeout=60,
    )
    known = {ln.strip() for ln in known_raw.splitlines() if ln.strip()}
    dump_raw = _exec(queen, DUMP_SH, timeout=30)
    allowed, _, hs = dump_raw.partition("---HS---")
    peers = parse_wg_show_dump(allowed, hs)
    cands = select_gc_extra_pubs(peers, known)
    never = [p for p in peers if p.pub in cands and p.handshake_age is None]
    stale = [p for p in peers if p.pub in cands and p.handshake_age is not None]
    to_drop = [p.pub for p in peers if p.pub in cands]
    print(
        f"dump={len(peers)} known_device_keys={len(known)} "
        f"extras_never={len(never)} extras_stale6h={len(stale)} drop={len(to_drop)}"
    )
    if not to_drop:
        print("nothing to drop")
        print("=== after ===")
        print(_exec(queen, AGES_SH).strip())
        queen.close()
        return

    batch = 40
    removed = 0
    left = set(to_drop)
    for i in range(0, len(to_drop), batch):
        chunk = to_drop[i : i + batch]
        parts = " ".join(f"peer {shlex.quote(p)} remove" for p in chunk)
        _exec(queen, f"wg set wdtt0 {parts}", timeout=60)
        after_raw = _exec(queen, "wg show wdtt0 latest-handshakes", timeout=30)
        present = set()
        for line in after_raw.splitlines():
            pub = line.split()[0] if line.split() else ""
            if pub:
                present.add(pub)
        gone = [p for p in chunk if p not in present]
        removed += len(gone)
        left -= set(gone)
        print(f"batch {i // batch + 1}: removed {len(gone)}/{len(chunk)}")

    print(f"removed_total={removed} still_listed={len(left)}")
    print("=== after ===")
    print(_exec(queen, AGES_SH).strip())
    print("wdtt still", _exec(queen, "systemctl is-active wdtt").strip())
    queen.close()


if __name__ == "__main__":
    main()
