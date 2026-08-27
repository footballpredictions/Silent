"""Drop live WireGuard peers when subscription is revoked.

HTTP from the excluded Android app cannot reach 10.66.66.1 on LTE.
GETCONF/keepalive is in-band; this module cuts the data plane on the host/cells.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
import subprocess
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import decrypt_value
from app.models import Device, HiveCell, User
from app.services.hive_incidents import push_incident
from app.services.hive_provision_service import _run as ssh_run
from app.services.hive_provision_service import _ssh_connect
from app.services.hive_service import _validate_outbound_url, get_queen_cell, resolve_ssh_password
from app.services.vpn_kick_select import (
    LivePeer,
    addr_ip,
    parse_wg_show_dump,
    select_extra_by_last_connected,
    select_owned_getconf_extras,
    select_resurrected_extras,
    should_keep_vpn_dataplane,
    snapshot_ages,
    snapshot_appeared,
    valid_wg_pub,
)

logger = logging.getLogger(__name__)
_recent_queen_kicks: dict[str, float] = {}
_NSENTER_HELPER = "silent-nsenter"
_WATCH_SEC = 25 * 60
_watch_until: dict[str, float] = {}
_watch_node: dict[str, str] = {}
_bound_extras: dict[str, set[str]] = {}
_peer_snapshot: dict[str, set[str]] = {}
_peer_ages: dict[str, dict[str, float | None]] = {}
_QUEEN_NODE = "queen"
_sync_unpaid_lock = asyncio.Lock()


def watch_device_revoke(device_id, *, node_key: str = "") -> None:
    did = str(device_id)
    _watch_until[did] = time.monotonic() + _WATCH_SEC
    if node_key:
        _watch_node[did] = node_key


def clear_device_revoke_watch(device_id) -> None:
    did = str(device_id)
    _watch_until.pop(did, None)
    _watch_node.pop(did, None)
    _bound_extras.pop(did, None)


def device_is_watched(device_id) -> bool:
    until = _watch_until.get(str(device_id), 0.0)
    return time.monotonic() < until


def _bind_extra_pub(device_id, pub: str) -> None:
    p = (pub or "").strip()
    if not _valid_wg_pub(p):
        return
    did = str(device_id)
    _bound_extras.setdefault(did, set()).add(p)
    watch_device_revoke(did)


def _bound_pubs_for(device_id) -> set[str]:
    return set(_bound_extras.get(str(device_id), set()))


def _unique_watch_on_node(node_key: str, device_id) -> bool:
    did = str(device_id)
    now = time.monotonic()
    others = [
        d for d, until in _watch_until.items()
        if until > now and _watch_node.get(d) == node_key and d != did
    ]
    return not others


def _note_snapshot(node_key: str, live: list[_LivePeer]) -> tuple[set[str], dict[str, float | None]]:
    cur = {p.pub for p in live if _valid_wg_pub(p.pub)}
    appeared, snap = snapshot_appeared(_peer_snapshot.get(node_key), cur)
    prev_ages = dict(_peer_ages.get(node_key) or {})
    _peer_snapshot[node_key] = snap
    _peer_ages[node_key] = snapshot_ages(live)
    return appeared, prev_ages


_WG_KICK_BY_IP_SH = (
    "ok=1; "
    'if [ -n "$1" ]; then wg set wdtt0 peer "$1" remove && ok=0; fi; '
    'if [ -n "$2" ]; then '
    'pubs=$(wg show wdtt0 allowed-ips 2>/dev/null | awk -v ip="$2" \''
    "{ n=split($2,a,\",\"); for(i=1;i<=n;i++){ cidr=a[i]; sub(/\\/.*/,\"\",cidr); "
    "if(cidr==ip) print $1 } }'"
    "); "
    'for p in $pubs; do wg set wdtt0 peer "$p" remove && ok=0; done; '
    "fi; exit $ok"
)

_valid_wg_pub = valid_wg_pub
_addr_ip = addr_ip
_LivePeer = LivePeer


def _ensure_nsenter_helper() -> bool:
    """Один alpine с nsenter/wg, --network host — без apk и без docker0 на каждый kick/GC."""
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", _NSENTER_HELPER],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if (r.stdout or "").strip() == "true":
        return True
    subprocess.run(["docker", "rm", "-f", _NSENTER_HELPER], capture_output=True, timeout=20)
    started = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", _NSENTER_HELPER,
            "--privileged", "--pid=host", "--network", "host",
            "--restart", "unless-stopped",
            "alpine:3.19",
            "sh", "-c",
            "apk add -q --no-cache util-linux wireguard-tools && exec sleep infinity",
        ],
        capture_output=True,
        timeout=90,
    )
    if started.returncode != 0:
        err = (started.stderr or started.stdout or b"").decode("utf-8", errors="replace")[:240]
        logger.warning("nsenter helper start failed: %s", err)
        return False
    for _ in range(20):
        ready = subprocess.run(
            ["docker", "exec", _NSENTER_HELPER, "sh", "-c", "command -v nsenter && command -v wg"],
            capture_output=True,
            timeout=10,
        )
        if ready.returncode == 0:
            return True
        time.sleep(0.3)
    logger.warning("nsenter helper not ready")
    return False


def _nsenter_host(script: str, *args: str, timeout: int = 45) -> subprocess.CompletedProcess:
    if not _ensure_nsenter_helper():
        raise RuntimeError("nsenter helper unavailable")
    cmd = [
        "docker", "exec", _NSENTER_HELPER,
        "nsenter", "-t", "1", "-m", "-n", "--",
        "sh", "-c", script, "_", *args,
    ]
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _ssh_wg_dump(host: str, password: str) -> list[_LivePeer]:
    client = _ssh_connect(host, password)
    try:
        _, allowed, _ = ssh_run(client, "wg show wdtt0 allowed-ips", timeout=20)
        _, hs, _ = ssh_run(client, "wg show wdtt0 latest-handshakes", timeout=20)
        return parse_wg_show_dump(allowed or "", hs or "")
    finally:
        client.close()


def _queen_wg_dump() -> list[_LivePeer]:
    try:
        r = _nsenter_host(
            "wg show wdtt0 allowed-ips; echo ---HS---; wg show wdtt0 latest-handshakes",
            timeout=45,
        )
    except Exception as e:
        logger.warning("queen wg dump error: %s", e)
        return []
    out = (r.stdout or b"").decode("utf-8", errors="replace")
    allowed, _, hs = out.partition("---HS---")
    return parse_wg_show_dump(allowed, hs)


def kick_wg_peer_on_queen(public_key: str, *, allowed_ip: str = "", force: bool = False) -> bool:
    """Remove a peer from host wdtt0 via docker nsenter (API → host netns + host wg)."""
    pub = (public_key or "").strip()
    ip = _addr_ip(allowed_ip)
    if not _valid_wg_pub(pub) and not ip:
        return False
    now = time.monotonic()
    if pub and not force and now - _recent_queen_kicks.get(pub, 0) < 5:
        return True
    try:
        r = _nsenter_host(_WG_KICK_BY_IP_SH, pub, ip, timeout=45)
        if r.returncode == 0:
            if pub:
                _recent_queen_kicks[pub] = time.monotonic()
            logger.warning("queen wg kick ok peer=%s ip=%s", (pub[:12] + "…") if pub else "-", ip or "-")
            return True
        err = (r.stderr or r.stdout or b"").decode("utf-8", errors="replace")[:240]
        logger.warning("queen wg kick failed peer=%s ip=%s rc=%s %s", pub[:12], ip, r.returncode, err)
        return False
    except Exception as e:
        logger.warning("queen wg kick error peer=%s: %s", pub[:12], e)
        return False


def remove_wg_peers_batch_on_queen(pubs: list[str], *, batch: int = 40) -> int:
    """Снять пачку GETCONF-мусора одним nsenter. Не рестартит wdtt."""
    keys = [p.strip() for p in pubs if _valid_wg_pub(p)]
    if not keys:
        return 0
    removed = 0
    for i in range(0, len(keys), max(1, batch)):
        chunk = keys[i : i + batch]
        parts = " ".join(f"peer {shlex.quote(p)} remove" for p in chunk)
        inner = f"wg set wdtt0 {parts}"
        try:
            r = _nsenter_host(inner, timeout=60)
            if r.returncode == 0:
                removed += len(chunk)
            else:
                err = (r.stderr or r.stdout or b"").decode("utf-8", errors="replace")[:240]
                logger.warning("queen wg gc batch failed n=%s rc=%s %s", len(chunk), r.returncode, err)
        except Exception as e:
            logger.warning("queen wg gc batch error: %s", e)
    return removed


def kick_wg_peer_via_ssh(host: str, password: str, public_key: str, *, allowed_ip: str = "") -> bool:
    """Снять peer на соте тем же SSH, что провижининг — не ждём обновления cell-agent."""
    pub = (public_key or "").strip()
    ip = _addr_ip(allowed_ip)
    if not host or not password:
        return False
    if not _valid_wg_pub(pub) and not ip:
        return False
    client = _ssh_connect(host, password)
    try:
        ok = False
        if _valid_wg_pub(pub):
            code, _, err = ssh_run(
                client,
                f"wg set wdtt0 peer {shlex.quote(pub)} remove",
                timeout=20,
            )
            if code == 0:
                ok = True
            else:
                logger.warning("ssh wg kick %s peer=%s… rc=%s %s", host, pub[:12], code, (err or "")[:160])
        if ip:
            cmd = (
                "ok=1; "
                "pubs=$(wg show wdtt0 allowed-ips 2>/dev/null | "
                f"awk -v ip={shlex.quote(ip)} "
                "'{ n=split($2,a,\",\"); for(i=1;i<=n;i++){ cidr=a[i]; "
                "sub(/\\/.*/,\"\",cidr); if(cidr==ip) print $1 } }'); "
                'for p in $pubs; do wg set wdtt0 peer "$p" remove && ok=0; done; '
                "exit $ok"
            )
            code, _, err = ssh_run(client, cmd, timeout=20)
            if code == 0:
                ok = True
            else:
                logger.warning("ssh wg kick-by-ip %s ip=%s rc=%s %s", host, ip, code, (err or "")[:160])
        if ok:
            logger.warning("ssh wg kick ok host=%s peer=%s ip=%s", host, (pub[:12] + "…") if pub else "-", ip or "-")
        return ok
    finally:
        client.close()


async def kick_wg_peer_on_cell(cell: HiveCell, public_key: str, *, allowed_ip: str = "") -> bool:
    host = (cell.public_ip or "").strip()
    pwd = resolve_ssh_password(cell)
    ok = False
    if host and pwd:
        try:
            ok = await asyncio.to_thread(
                kick_wg_peer_via_ssh, host, pwd, public_key, allowed_ip=allowed_ip
            )
        except Exception as e:
            logger.warning("ssh wg kick %s error: %s", cell.name, e)
    if ok:
        return True

    pub = (public_key or "").strip()
    ip = _addr_ip(allowed_ip)
    if cell.is_queen or not cell.api_url:
        return False
    if not _valid_wg_pub(pub) and not ip:
        return False
    secret = ""
    if cell.api_secret_enc:
        try:
            secret = decrypt_value(cell.api_secret_enc)
        except Exception:
            return False
    if not secret:
        return False
    try:
        base = _validate_outbound_url(cell.api_url)
    except ValueError:
        return False
    url = f"{base}/v1/wg/kick"
    timeout = settings.HIVE_CELL_HTTP_TIMEOUT_SEC
    try:
        payload = {"wg_public_key": pub or ""}
        ip = _addr_ip(allowed_ip)
        if ip:
            payload["allowed_ip"] = ip
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.post(
                url,
                headers={"X-Cell-Agent-Secret": secret},
                json=payload,
            )
        if resp.status_code >= 400:
            logger.warning("cell-agent wg kick %s HTTP %s", cell.name, resp.status_code)
            return False
        data = resp.json() if resp.content else {}
        ok = bool(data.get("ok", True))
        if ok:
            logger.warning("cell-agent wg kick ok %s peer=%s…", cell.name, pub[:12])
        return ok
    except Exception as e:
        logger.warning("cell-agent wg kick %s failed: %s", cell.name, e)
        return False


async def _known_wg_pubs(db: AsyncSession, *, except_device_id=None) -> set[str]:
    q = select(Device.wg_public_key).where(Device.is_active == True)  # noqa: E712
    result = await db.execute(q)
    out: set[str] = set()
    for (raw,) in result.all():
        p = (raw or "").strip()
        if _valid_wg_pub(p):
            out.add(p)
    return out


async def _cell_has_other_recent_clients(db: AsyncSession, device: Device) -> bool:
    if device.cell_id is None:
        return False
    cutoff = time.time() - 3600
    from datetime import datetime, timezone

    result = await db.execute(
        select(Device).where(
            Device.cell_id == device.cell_id,
            Device.is_active == True,  # noqa: E712
            Device.user_id != device.user_id,
        )
    )
    for other in result.scalars().all():
        ts = other.last_connected or other.created_at
        if ts is None:
            continue
        if ts.tzinfo is None:
            epoch = ts.replace(tzinfo=timezone.utc).timestamp()
        else:
            epoch = ts.timestamp()
        if epoch >= cutoff:
            return True
    return False


async def _dump_node_peers(db: AsyncSession, *, on_queen: bool, cell: HiveCell | None) -> list[_LivePeer]:
    if on_queen or cell is None:
        try:
            return await asyncio.to_thread(_queen_wg_dump)
        except Exception as e:
            logger.warning("queen dump for kick failed: %s", e)
            return []
    host = (cell.public_ip or "").strip()
    pwd = resolve_ssh_password(cell)
    if not host or not pwd:
        return []
    try:
        return await asyncio.to_thread(_ssh_wg_dump, host, pwd)
    except Exception as e:
        logger.warning("cell dump for kick %s failed: %s", cell.name, e)
        return []


async def _kick_pubs_and_ip(
    *,
    on_queen: bool,
    cell: HiveCell | None,
    pubs: list[str],
    allowed_ip: str,
    force: bool,
) -> bool:
    ok = False
    ip = _addr_ip(allowed_ip)
    if on_queen or cell is None:
        for p in pubs:
            if kick_wg_peer_on_queen(p, force=force):
                ok = True
        if ip:
            if kick_wg_peer_on_queen("", allowed_ip=ip, force=force):
                ok = True
        return ok
    if cell is None:
        return False
    for p in pubs:
        if await kick_wg_peer_on_cell(cell, p, allowed_ip=""):
            ok = True
    if ip:
        if await kick_wg_peer_on_cell(cell, "", allowed_ip=ip):
            ok = True
    return ok


async def kick_device_peers(
    db: AsyncSession,
    device: Device,
    *,
    force: bool = False,
    bind_new: bool = True,
    session_last_connected=None,
) -> bool:
    """Cut this device's dataplane: known WG key, exact assigned IP, owned GETCONF extras.

    Never picks “newest extra on the node” (incident 2026-08-16). Extra is owned if
    its allowed-ips IP matches the device, we already bound it, it uniquely
    appeared, leftover handshake ≈ last_connected, or a unique stale extra resurrected.
    """
    pub = (device.wg_public_key or "").strip()
    addr = device.wg_address or ""
    live_pub = (getattr(device, "wg_live_public_key", None) or "").strip()
    live_addr = getattr(device, "wg_live_address", None) or ""
    queen = await get_queen_cell(db)
    on_queen = device.cell_id is None or (queen is not None and device.cell_id == queen.id)
    cell = None if on_queen else (
        await db.get(HiveCell, device.cell_id) if device.cell_id is not None else None
    )
    node_key = _QUEEN_NODE if on_queen or cell is None else str(cell.id)

    known = await _known_wg_pubs(db)
    live = await _dump_node_peers(db, on_queen=on_queen, cell=cell)
    appeared, prev_ages = _note_snapshot(node_key, live) if bind_new else (set(), {})
    bound = _bound_pubs_for(device.id)
    if _valid_wg_pub(live_pub):
        bound.add(live_pub)
    last_ts = session_last_connected if session_last_connected is not None else device.last_connected
    if bind_new:
        watch_device_revoke(device.id, node_key=node_key)
    owned = select_owned_getconf_extras(
        live,
        known_pubs=known,
        device_ip=addr,
        appeared_pubs=appeared,
        bound_pubs=bound,
        unique_watch_on_node=bind_new and _unique_watch_on_node(node_key, device.id),
    )
    if bind_new:
        for extra in select_extra_by_last_connected(live, last_ts, known):
            owned.append(extra)
        for extra in select_resurrected_extras(live, prev_ages, known):
            owned.append(extra)
    extra_pubs = []
    for p in owned:
        if _valid_wg_pub(p.pub) and p.pub not in extra_pubs:
            extra_pubs.append(p.pub)
            _bind_extra_pub(device.id, p.pub)
            if p.ip:
                try:
                    device.wg_live_public_key = p.pub
                    device.wg_live_address = p.ip
                except Exception:
                    pass

    pubs = []
    for p in [pub, live_pub, *_bound_pubs_for(device.id), *extra_pubs]:
        if _valid_wg_pub(p) and p not in pubs:
            pubs.append(p)
    ip = _addr_ip(addr) or _addr_ip(live_addr)
    extra_ips = [i for i in [_addr_ip(addr), _addr_ip(live_addr)] if i]
    try:
        from app.services.vpn_deny_net import collect_ips, read_host_wdtt_identities

        _ensure_nsenter_helper()
        rec = read_host_wdtt_identities([str(device.id)]).get(str(device.id)) or {}
        if _valid_wg_pub(rec.get("pub") or ""):
            if rec["pub"] not in pubs:
                pubs.append(rec["pub"])
            _bind_extra_pub(device.id, rec["pub"])
        extra_ips = list(dict.fromkeys([*extra_ips, *collect_ips(rec.get("ip"))]))
    except Exception as e:
        logger.debug("wdtt identity for kick: %s", e)
    if not pubs and not extra_ips:
        logger.warning("vpn kick skip device %s — no wg key/address", device.id)
        return False

    ok = await _kick_pubs_and_ip(
        on_queen=on_queen, cell=cell, pubs=pubs, allowed_ip=ip, force=force,
    )
    for extra_ip in extra_ips:
        if extra_ip != ip:
            more = await _kick_pubs_and_ip(
                on_queen=on_queen, cell=cell, pubs=[], allowed_ip=extra_ip, force=force,
            )
            ok = ok or more
    # GETCONF extra may sit on the other node after server switch.
    if cell is not None:
        extra_ok = await _kick_pubs_and_ip(
            on_queen=True, cell=None, pubs=pubs, allowed_ip=ip, force=force,
        )
        ok = ok or extra_ok
        for extra_ip in extra_ips:
            if extra_ip != ip:
                more = await _kick_pubs_and_ip(
                    on_queen=True, cell=None, pubs=[], allowed_ip=extra_ip, force=force,
                )
                ok = ok or more
    elif on_queen:
        if device.cell_id is not None and queen is not None and device.cell_id != queen.id:
            other = await db.get(HiveCell, device.cell_id)
            if other is not None:
                extra_ok = await _kick_pubs_and_ip(
                    on_queen=False, cell=other, pubs=pubs, allowed_ip=ip, force=force,
                )
                ok = ok or extra_ok
    return ok


async def remember_device_live_peer(db: AsyncSession, device: Device) -> bool:
    """On toggle-off: bind leftover GETCONF extra (cache will reuse it)."""
    queen = await get_queen_cell(db)
    on_queen = device.cell_id is None or (queen is not None and device.cell_id == queen.id)
    cell = None if on_queen else (
        await db.get(HiveCell, device.cell_id) if device.cell_id is not None else None
    )
    node_key = _QUEEN_NODE if on_queen or cell is None else str(cell.id)
    known = await _known_wg_pubs(db)
    live = await _dump_node_peers(db, on_queen=on_queen, cell=cell)
    _note_snapshot(node_key, live)
    hits = select_extra_by_last_connected(live, device.last_connected, known)
    if not hits:
        hits = select_owned_getconf_extras(
            live, known_pubs=known, device_ip=device.wg_address or "",
        )
    if len(hits) != 1:
        return False
    peer = hits[0]
    device.wg_live_public_key = peer.pub
    device.wg_live_address = peer.ip or None
    _bind_extra_pub(device.id, peer.pub)
    logger.warning(
        "vpn remember live extra device=%s peer=%s ip=%s",
        device.id,
        peer.pub[:12] + "…",
        peer.ip or "-",
    )
    return True


async def refresh_peer_snapshots(db: AsyncSession) -> None:
    """Keep handshake ages so leftover extras can be recognized after toggle-on."""
    try:
        live = await _dump_node_peers(db, on_queen=True, cell=None)
        _note_snapshot(_QUEEN_NODE, live)
    except Exception as e:
        logger.debug("queen snapshot refresh: %s", e)


async def sync_unpaid_deny_net(db: AsyncSession) -> int:
    """DROP inner WG IPs of unpaid devices on the queen only.

    IPs come only from wdtt passwords.json (the address GETCONF actually issues).
    Do not use DB wg_address / leftover live IPs and do not SSH the set onto cells:
    that blocked the API event loop and dropped paying users (2026-08-19).
    """
    from app.services.vpn_deny_net import (
        read_host_wdtt_identities,
        sync_queen_deny_ips,
        unpaid_ips_from_wdtt_only,
    )

    if _sync_unpaid_lock.locked():
        return 0
    result = await db.execute(select(Device).where(Device.is_active == True))  # noqa: E712
    devices = [
        d for d in result.scalars().all()
        if not (d.device_fingerprint or "").startswith("boot:")
    ]
    if not devices:
        _ensure_nsenter_helper()
        return await asyncio.to_thread(sync_queen_deny_ips, set())
    from app.services.subscription_service import users_with_vpn_access_ids

    allowed = await users_with_vpn_access_ids(db)
    unpaid: list[Device] = [d for d in devices if d.user_id not in allowed]
    _ensure_nsenter_helper()
    idents = read_host_wdtt_identities([str(d.id) for d in unpaid])
    ips = unpaid_ips_from_wdtt_only(idents)

    def _kick_and_sync() -> int:
        for rec in idents.values():
            pub = rec.get("pub") or ""
            if _valid_wg_pub(pub):
                kick_wg_peer_on_queen(pub, force=True)
            ip = rec.get("ip") or ""
            if ip:
                kick_wg_peer_on_queen("", allowed_ip=ip, force=True)
        return sync_queen_deny_ips(ips)

    if _sync_unpaid_lock.locked():
        return 0
    async with _sync_unpaid_lock:
        return await asyncio.to_thread(_kick_and_sync)


async def restore_user_vpn_dataplane(db: AsyncSession, user: User) -> None:
    """После выдачи подписки/теста: снять watch и DROP, обновить manifest сот."""
    result = await db.execute(select(Device).where(Device.user_id == user.id))
    cell_ids: set = set()
    for device in result.scalars().all():
        clear_device_revoke_watch(device.id)
        if device.cell_id is not None:
            cell_ids.add(device.cell_id)
    from app.services.hive_cell_sync import invalidate_manifest_cache, sync_cell_manifest_by_id

    invalidate_manifest_cache()
    for cid in cell_ids:
        try:
            await sync_cell_manifest_by_id(db, cid)
        except Exception as e:
            logger.warning("manifest push after restore failed: %s", e)
    try:
        await sync_unpaid_deny_net(db)
    except Exception as e:
        logger.warning("silent deny after restore: %s", e)


async def kick_user_vpn_sessions(db: AsyncSession, user: User) -> int:
    """Cut live WG sessions for a user and push vpn_allowed=false to cells."""
    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.is_active == True,  # noqa: E712
        )
    )
    devices = list(result.scalars().all())
    kicked = 0
    cell_ids: set = set()
    for device in devices:
        fp = device.device_fingerprint or ""
        if fp.startswith("boot:"):
            continue
        if not (getattr(device, "wg_live_public_key", None) or "").strip():
            try:
                await remember_device_live_peer(db, device)
            except Exception:
                pass
        ok = await kick_device_peers(db, device, force=True, bind_new=True)
        logger.warning(
            "vpn kick device user=%s type=%s cell=%s key=%s ok=%s",
            user.email,
            device.device_type,
            device.cell_id,
            ((device.wg_public_key or "")[:12] + "…") if device.wg_public_key else "-",
            ok,
        )
        if ok:
            kicked += 1
        if device.cell_id is not None:
            cell_ids.add(device.cell_id)
    from app.services.hive_cell_sync import invalidate_manifest_cache, sync_cell_manifest_by_id

    try:
        await db.commit()
    except Exception:
        await db.rollback()
    invalidate_manifest_cache()
    for cid in cell_ids:
        try:
            await sync_cell_manifest_by_id(db, cid)
        except Exception as e:
            logger.warning("manifest push after kick failed: %s", e)
    logger.warning("vpn kick done user=%s removed=%s of %s", user.email, kicked, len(devices))
    try:
        await sync_unpaid_deny_net(db)
    except Exception as e:
        logger.warning("silent deny after kick: %s", e)
    if kicked:
        push_incident(
            source="vpn.kick",
            severity="info",
            message=f"Сняты живые VPN-сессии после отзыва подписки ({kicked})",
            details=user.email,
        )
    return kicked


async def kick_connected_without_subscription(db: AsyncSession) -> int:
    """Страховка: нет подписки → срезать dataplane по ключу и точному IP.

    Не трогаем админов, тестовый режим и живой plan=test.
    bind_new=False: не угадываем новый extra на тихой соте (2026-08-16 / 2026-08-23).
    """
    cutoff = datetime.utcnow() - timedelta(minutes=20)
    result = await db.execute(
        select(Device).where(
            Device.is_active == True,  # noqa: E712
            or_(
                Device.is_connected == True,  # noqa: E712
                Device.last_connected >= cutoff,
            ),
        )
    )
    devices = list(result.scalars().all())
    watched_ids = {d for d, until in _watch_until.items() if until > time.monotonic()}
    extra_ids: list = []
    if watched_ids:
        extra_q = await db.execute(
            select(Device).where(Device.is_active == True)  # noqa: E712
        )
        for d in extra_q.scalars().all():
            if str(d.id) in watched_ids and d not in devices:
                extra_ids.append(d)
    devices = devices + extra_ids
    if not devices:
        return 0
    from app.services.subscription_service import users_with_vpn_access_ids

    allowed = await users_with_vpn_access_ids(db)
    kicked = 0
    cell_ids: set = set()
    seen: set[str] = set()
    for device in devices:
        did = str(device.id)
        if did in seen:
            continue
        seen.add(did)
        if (device.device_fingerprint or "").startswith("boot:"):
            continue
        if device.user_id in allowed:
            continue
        if not await kick_device_peers(db, device, force=True, bind_new=False):
            continue
        device.is_connected = False
        kicked += 1
        if device.cell_id is not None:
            cell_ids.add(device.cell_id)
    if kicked:
        await db.commit()
        logger.warning("vpn kick sweeper: %s device(s) without subscription", kicked)
        from app.services.hive_cell_sync import invalidate_manifest_cache, sync_cell_manifest_by_id

        invalidate_manifest_cache()
        for cid in cell_ids:
            try:
                await sync_cell_manifest_by_id(db, cid)
            except Exception as e:
                logger.warning("manifest push after sweeper kick failed: %s", e)
    if not getattr(kick_connected_without_subscription, "_deny_fail_open", False):
        try:
            from app.services.vpn_deny_net import disable_queen_deny

            _ensure_nsenter_helper()
            disable_queen_deny()
            logger.warning("silent deny fail-open: queen SILENT_DENY removed")
        except Exception as e:
            logger.warning("silent deny fail-open: %s", e)
        kick_connected_without_subscription._deny_fail_open = True  # type: ignore[attr-defined]
    return kicked


async def kick_if_subscription_denied(
    db: AsyncSession,
    device: Device,
    *,
    session_last_connected=None,
) -> bool:
    """Immediate cut when wdtt reports online for a user without subscription."""
    did = str(device.id)
    now = time.monotonic()
    last: dict[str, float] = getattr(kick_if_subscription_denied, "_last", {})
    if now - last.get(did, 0) < 8:
        return False
    last[did] = now
    kick_if_subscription_denied._last = last  # type: ignore[attr-defined]
    ok = await kick_device_peers(
        db, device, force=True, bind_new=False, session_last_connected=session_last_connected,
    )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
    from app.services.hive_cell_sync import invalidate_manifest_cache, sync_cell_manifest_by_id

    invalidate_manifest_cache()
    if device.cell_id is not None:
        try:
            await sync_cell_manifest_by_id(db, device.cell_id)
        except Exception as e:
            logger.warning("manifest push after unpaid online kick failed: %s", e)
    try:
        await sync_unpaid_deny_net(db)
    except Exception as e:
        logger.warning("silent deny after unpaid online: %s", e)
    return ok

