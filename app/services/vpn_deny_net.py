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
import os
import subprocess
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CHAIN = "SILENT_DENY"
_DENY_NET = ipaddress.ip_network("10.66.0.0/16")
# 10.66.66.2 — дефолт manifest, если у устройства нет своего адреса; DROP его роняет чужих.
_PROTECTED = frozenset({"10.66.66.1", "10.66.66.0", "10.66.66.2", "0.0.0.0"})
_WDTT_PASSWORDS = "/etc/wdtt/passwords.json"
_NSENTER_HELPER = "silent-nsenter"
_last_queen_ips: frozenset[str] | None = None
DELETED_DEVICE_PREFIX = "vpn_deleted_device:"
# Orphan identities survive account deletion. Batch restore keeps this bounded
# without the old per-rule shell/argv limit at 2000 addresses.
MAX_DENY_IPS = 10_000


def canonical_device_ids(values) -> list[str]:
    """Deletion records identify only registered UUID devices, never bootstrap refs."""
    out = set()
    for value in values:
        try:
            out.add(str(uuid.UUID(str(value))))
        except (ValueError, TypeError, AttributeError):
            continue
    return sorted(out)


async def remember_deleted_device_ids(db, device_ids) -> int:
    """Persist UUID-only deny records in the same transaction as account deletion."""
    from sqlalchemy.dialects.postgresql import insert
    from app.models import AppSetting

    ids = canonical_device_ids(device_ids)
    if not ids:
        return 0
    result = await db.execute(
        insert(AppSetting).values([
            {"key": DELETED_DEVICE_PREFIX + did, "value": "deleted"} for did in ids
        ]).on_conflict_do_nothing(index_elements=[AppSetting.key]).returning(AppSetting.key)
    )
    count = len(result.scalars().all())
    if count:
        from app.services.hive_cell_sync import invalidate_manifest_cache
        invalidate_manifest_cache()
    return count


async def deleted_device_ids(db) -> list[str]:
    from sqlalchemy import select
    from app.models import AppSetting

    result = await db.execute(select(AppSetting.key).where(AppSetting.key.startswith(DELETED_DEVICE_PREFIX)))
    return canonical_device_ids(key[len(DELETED_DEVICE_PREFIX):] for key in result.scalars().all())


def deleted_manifest_entries(device_ids, *, existing_ids=()) -> list[dict]:
    existing = set(map(str, existing_ids))
    return [
        {"id": did, "user_id": "", "wg_public_key": "", "wg_address": "10.66.66.2/32",
         "is_connected": False, "vpn_allowed": False}
        for did in canonical_device_ids(device_ids) if did not in existing
    ]


def denied_identity_ips(identities, allowed_device_ids) -> set[str]:
    """Exact wdtt IPs, including deleted rows; never deny an IP shared by allowed peers."""
    allowed = set(map(str, allowed_device_ids))
    permitted = unpaid_ips_from_wdtt_only({k: v for k, v in identities.items() if k in allowed})
    denied = unpaid_ips_from_wdtt_only({k: v for k, v in identities.items() if k not in allowed})
    return denied - permitted


@dataclass(frozen=True)
class IdentitiesRead:
    ok: bool
    identities: dict[str, dict[str, str]]
    error: str = ""


def deny_ids_tmp_path() -> str:
    """Уникальный файл на каждый вызов: общий /tmp/silent-deny-ids.json скрещивал параллельные чтения."""
    return f"/tmp/silent-deny-ids-{os.getpid()}-{uuid.uuid4().hex}.json"


_DISABLE_SH = (
    f"iptables -F {CHAIN} 2>/dev/null || true; "
    f"while iptables -C FORWARD -j {CHAIN} 2>/dev/null; do "
    f"iptables -D FORWARD -j {CHAIN} || break; done"
)


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


def unpaid_ips_from_wdtt_only(idents: dict[str, dict[str, str]]) -> set[str]:
    """Только inner-IP из passwords.json. Не брать wg_address / leftover live."""
    ips: set[str] = set()
    for rec in idents.values():
        if not isinstance(rec, dict):
            continue
        ip = (rec.get("ip") or "").strip().split("/", 1)[0]
        if is_safe_deny_ip(ip):
            ips.add(ip)
    return ips


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
            "docker", "exec", "-i", _NSENTER_HELPER,
            "nsenter", "-t", "1", "-m", "-n", "--",
            "sh",
        ],
        input=script,
        capture_output=True,
        timeout=timeout,
        text=True,
    )


def read_host_wdtt_identities(device_ids: list[str]) -> dict[str, dict[str, str]]:
    return read_host_wdtt_identities_result(device_ids).identities


def read_host_wdtt_identities_result(device_ids: list[str] | None = None) -> IdentitiesRead:
    ids = None if device_ids is None else [str(i) for i in device_ids if str(i) and not str(i).startswith("boot:")]
    if ids == []:
        return IdentitiesRead(ok=True, identities={})
    payload = json.dumps(ids)
    tmp = deny_ids_tmp_path()
    write_script = (
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        f"Path({tmp!r}).write_text({payload!r})\n"
        "PY"
    )
    read_script = (
        "python3 - <<'PY'\n"
        "import json\n"
        "from pathlib import Path\n"
        f"p=Path({tmp!r})\n"
        "ids=json.loads(p.read_text())\n"
        "blob=json.load(open('/etc/wdtt/passwords.json'))\n"
        "devs=blob.get('devices') or {}\n"
        "if ids is None: ids=list(devs)\n"
        "out={}\n"
        "for i in ids:\n"
        "    if str(i).startswith('boot:'): continue\n"
        "    d=devs.get(i) or {}\n"
        "    if not isinstance(d, dict): continue\n"
        "    rec={}\n"
        "    ip=(d.get('ip') or '').split('/')[0].strip()\n"
        "    pub=(d.get('pub_key') or '').strip()\n"
        "    if ip: rec['ip']=ip\n"
        "    if pub: rec['pub']=pub\n"
        "    if rec: out[i]=rec\n"
        "print(json.dumps(out))\n"
        "p.unlink(missing_ok=True)\n"
        "PY"
    )
    try:
        wr = _nsenter(write_script, timeout=15)
        if wr.returncode != 0:
            err = (wr.stderr or "")[:160]
            logger.warning("wdtt identities write rc=%s %s", wr.returncode, err)
            return IdentitiesRead(ok=False, identities={}, error=err or "write_failed")
        r = _nsenter(read_script, timeout=20)
    except Exception as e:
        logger.warning("wdtt identities read failed: %s", e)
        return IdentitiesRead(ok=False, identities={}, error=str(e)[:200])
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[:200]
        logger.warning("wdtt identities rc=%s %s", r.returncode, err)
        return IdentitiesRead(ok=False, identities={}, error=err or "read_failed")
    try:
        raw = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception as e:
        return IdentitiesRead(ok=False, identities={}, error=str(e)[:160])
    if not isinstance(raw, dict):
        return IdentitiesRead(ok=False, identities={}, error="not_object")
    cleaned: dict[str, dict[str, str]] = {}
    for did, rec in raw.items():
        if ids is None and str(did) not in canonical_device_ids([did]):
            continue
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
    return IdentitiesRead(ok=True, identities=cleaned)


def _iptables_sync_script(ips: set[str]) -> str:
    safe = sorted(ip for ip in ips if is_safe_deny_ip(ip))
    lines = [
        "set -e",
        f"iptables -N {CHAIN} 2>/dev/null || true",
        "iptables-restore --noflush <<'SILENT_DENY_RULES'",
        "*filter",
        f":{CHAIN} - [0:0]",
        f"-F {CHAIN}",
    ]
    for ip in safe:
        lines.append(f"-A {CHAIN} -s {ip}/32 -j DROP")
        lines.append(f"-A {CHAIN} -d {ip}/32 -j DROP")
    lines.extend([
        "COMMIT", "SILENT_DENY_RULES",
        f"iptables -C FORWARD -j {CHAIN} 2>/dev/null || iptables -I FORWARD 1 -j {CHAIN}",
    ])
    return "\n".join(lines) + "\n"


def disable_queen_deny() -> None:
    """Снять SILENT_DENY с FORWARD. Не рестартит wdtt."""
    global _last_queen_ips
    try:
        r = _nsenter(_DISABLE_SH, timeout=20)
    except Exception as e:
        logger.warning("silent deny disable failed: %s", e)
        return
    if r.returncode != 0:
        logger.warning("silent deny disable rc=%s %s", r.returncode, (r.stderr or "")[:160])
        return
    _last_queen_ips = frozenset()


def sync_queen_deny_ips(ips: set[str]) -> int:
    """Rebuild host FORWARD chain. Empty set = nobody denied (fail-open)."""
    global _last_queen_ips
    safe = frozenset(ip for ip in ips if is_safe_deny_ip(ip))
    if _last_queen_ips is not None and safe == _last_queen_ips:
        return len(safe)
    if not safe:
        disable_queen_deny()
        return 0
    try:
        r = _nsenter(_iptables_sync_script(set(safe)), timeout=30)
    except Exception as e:
        logger.warning("silent deny sync failed: %s", e)
        return 0
    if r.returncode != 0:
        logger.warning("silent deny sync rc=%s %s", r.returncode, (r.stderr or "")[:200])
        return 0
    _last_queen_ips = safe
    logger.warning("silent deny queen ips=%s", len(safe))
    return len(safe)


def cell_sync_script(ips: set[str]) -> str:
    """Только локально на ноде. Улей не должен пушить этот скрипт на соты."""
    return _iptables_sync_script(ips)
