"""Dataplane deny for unpaid devices — iptables, no wdtt restart.

GETCONF with the master password always upserts the same peer for a device_id
(wdtt /etc/wdtt/passwords.json). Removing the WG peer is not enough: the next
GETCONF brings it back. Old clients ignore extra config headers.

Drop FORWARD for the exact inner IP from wdtt's devices map. Same device_id
always gets that IP, so old and new clients lose internet until the IP is
removed from the chain. Do not guess foreign GETCONF extras.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import subprocess

logger = logging.getLogger(__name__)

CHAIN = "SILENT_DENY"
_DENY_NET = ipaddress.ip_network("10.66.0.0/16")
_PROTECTED = frozenset({"10.66.66.1", "10.66.66.0", "0.0.0.0"})
_WDTT_PASSWORDS = "/etc/wdtt/passwords.json"
_NSENTER_HELPER = "silent-nsenter"


def is_safe_deny_ip(ip: str | None) -> bool:
    raw = (ip or "").strip().split("/", 1)[0]
    if not raw or raw in _PROTECTED:
        return False
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return False
    if addr.version != 4:
        return False
    return addr in _DENY_NET and str(addr) not in _PROTECTED


def collect_ips(*values: str | None) -> set[str]:
    out: set[str] = set()
    for value in values:
        raw = (value or "").strip().split("/", 1)[0]
        if is_safe_deny_ip(raw):
            out.add(raw)
    return out


def identities_from_wdtt_db(blob: dict, device_ids: list[str]) -> dict[str, dict[str, str]]:
    """device_id -> {ip, pub} from wdtt passwords.json (no secrets)."""
    devices = blob.get("devices") if isinstance(blob, dict) else None
    if not isinstance(devices, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for did in device_ids:
        key = str(did)
        if key.startswith("boot:"):
            continue
        row = devices.get(key)
        if not isinstance(row, dict):
            continue
        ip = (row.get("ip") or "").strip().split("/", 1)[0]
        pub = (row.get("pub_key") or "").strip()
        info: dict[str, str] = {}
        if is_safe_deny_ip(ip):
            info["ip"] = ip
        if pub:
            info["pub"] = pub
        if info:
            out[key] = info
    return out


def _nsenter(script: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker", "exec", _NSENTER_HELPER,
            "nsenter", "-t", "1", "-m", "-n", "--",
            "sh", "-c", script,
        ],
        capture_output=True,
        timeout=timeout,
        text=True,
    )


def read_host_wdtt_identities(device_ids: list[str]) -> dict[str, dict[str, str]]:
    ids = [str(i) for i in device_ids if str(i) and not str(i).startswith("boot:")]
    if not ids:
        return {}
    payload = json.dumps(ids)
    write_script = (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"Path('/tmp/silent-deny-ids.json').write_text({payload!r})\n"
        "PY"
    )
    read_script = (
        "python3 - <<'PY'\n"
        "import json\n"
        "from pathlib import Path\n"
        "ids=json.loads(Path('/tmp/silent-deny-ids.json').read_text())\n"
        "blob=json.load(open('/etc/wdtt/passwords.json'))\n"
        "devs=blob.get('devices') or {}\n"
        "out={}\n"
        "for i in ids:\n"
        "    d=devs.get(i) or {}\n"
        "    if not isinstance(d, dict): continue\n"
        "    rec={}\n"
        "    ip=(d.get('ip') or '').split('/')[0].strip()\n"
        "    pub=(d.get('pub_key') or '').strip()\n"
        "    if ip: rec['ip']=ip\n"
        "    if pub: rec['pub']=pub\n"
        "    if rec: out[i]=rec\n"
        "print(json.dumps(out))\n"
        "Path('/tmp/silent-deny-ids.json').unlink(missing_ok=True)\n"
        "PY"
    )
    try:
        wr = _nsenter(write_script, timeout=15)
        if wr.returncode != 0:
            logger.warning("wdtt identities write rc=%s %s", wr.returncode, (wr.stderr or "")[:160])
            return {}
        r = _nsenter(read_script, timeout=20)
    except Exception as e:
        logger.warning("wdtt identities read failed: %s", e)
        return {}
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[:200]
        logger.warning("wdtt identities rc=%s %s", r.returncode, err)
        return {}
    try:
        raw = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for did, rec in raw.items():
        if not isinstance(rec, dict):
            continue
        info: dict[str, str] = {}
        ip = (rec.get("ip") or "").strip()
        pub = (rec.get("pub") or "").strip()
        if is_safe_deny_ip(ip):
            info["ip"] = ip
        if pub:
            info["pub"] = pub
        if info:
            cleaned[str(did)] = info
    return cleaned


def _iptables_sync_script(ips: set[str]) -> str:
    safe = sorted(ip for ip in ips if is_safe_deny_ip(ip))
    lines = [
        f"iptables -N {CHAIN} 2>/dev/null || true",
        f"iptables -F {CHAIN}",
        (
            f"iptables -C FORWARD -j {CHAIN} 2>/dev/null || "
            f"iptables -I FORWARD 1 -j {CHAIN}"
        ),
    ]
    for ip in safe:
        lines.append(f"iptables -A {CHAIN} -s {ip}/32 -j DROP")
        lines.append(f"iptables -A {CHAIN} -d {ip}/32 -j DROP")
    return " ; ".join(lines)


def sync_queen_deny_ips(ips: set[str]) -> int:
    """Rebuild host FORWARD chain. Empty set = nobody denied (fail-open)."""
    safe = {ip for ip in ips if is_safe_deny_ip(ip)}
    try:
        r = _nsenter(_iptables_sync_script(safe), timeout=30)
    except Exception as e:
        logger.warning("silent deny sync failed: %s", e)
        return 0
    if r.returncode != 0:
        logger.warning("silent deny sync rc=%s %s", r.returncode, (r.stderr or "")[:200])
        return 0
    if safe:
        logger.warning("silent deny queen ips=%s", len(safe))
    return len(safe)


def cell_sync_script(ips: set[str]) -> str:
    return _iptables_sync_script(ips)
