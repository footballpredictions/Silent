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
from datetime import timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import decrypt_value
from app.models import Device, HiveCell, User
from app.services.hive_incidents import push_incident
from app.services.hive_provision_service import _run as ssh_run
from app.services.hive_provision_service import _ssh_connect
from app.services.hive_service import _validate_outbound_url, get_queen_cell, resolve_ssh_password
from app.services.subscription_service import user_has_active_subscription
from app.services.vpn_kick_select import (
    LivePeer,
    addr_ip,
    parse_wg_show_dump,
    valid_wg_pub,
)

logger = logging.getLogger(__name__)
_recent_queen_kicks: dict[str, float] = {}

_valid_wg_pub = valid_wg_pub
_addr_ip = addr_ip
_LivePeer = LivePeer


def _ssh_wg_dump(host: str, password: str) -> list[_LivePeer]:
    client = _ssh_connect(host, password)
    try:
        _, allowed, _ = ssh_run(client, "wg show wdtt0 allowed-ips", timeout=20)
        _, hs, _ = ssh_run(client, "wg show wdtt0 latest-handshakes", timeout=20)
        return parse_wg_show_dump(allowed or "", hs or "")
    finally:
        client.close()


def _queen_wg_dump() -> list[_LivePeer]:
    r = subprocess.run(
        [
            "docker", "run", "--rm", "--privileged", "--pid=host",
            "alpine:3.19",
            "sh", "-c",
            "apk add -q --no-cache util-linux >/dev/null 2>&1 || true; "
            "nsenter -t 1 -m -n -- sh -c "
            "'wg show wdtt0 allowed-ips; echo ---HS---; wg show wdtt0 latest-handshakes'",
        ],
        capture_output=True,
        timeout=45,
    )
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
    stamp = pub or ip
    if not force and stamp and now - _recent_queen_kicks.get(stamp, 0) < 90:
        return True
    inner = (
        "ok=1; "
        'if [ -n "$1" ]; then wg set wdtt0 peer "$1" remove && ok=0; fi; '
        'if [ -n "$2" ]; then '
        'p=$(wg show wdtt0 allowed-ips 2>/dev/null | awk -v ip="$2" \'$0 ~ ip {print $1; exit}\'); '
        'if [ -n "$p" ]; then wg set wdtt0 peer "$p" remove && ok=0; fi; '
        "fi; exit $ok"
    )
    try:
        r = subprocess.run(
            [
                "docker", "run", "--rm", "--privileged", "--pid=host",
                "alpine:3.19",
                "sh", "-c",
                "apk add -q --no-cache util-linux >/dev/null 2>&1 || true; "
                "nsenter -t 1 -m -n -- sh -c \"$0\" _ \"$1\" \"$2\"",
                inner,
                pub,
                ip,
            ],
            capture_output=True,
            timeout=45,
        )
        if r.returncode == 0:
            if stamp:
                _recent_queen_kicks[stamp] = time.monotonic()
            logger.warning("queen wg kick ok peer=%s ip=%s", (pub[:12] + "…") if pub else "-", ip or "-")
            return True
        err = (r.stderr or r.stdout or b"").decode("utf-8", errors="replace")[:240]
        logger.warning("queen wg kick failed peer=%s ip=%s rc=%s %s", pub[:12], ip, r.returncode, err)
        return False
    except Exception as e:
        logger.warning("queen wg kick error peer=%s: %s", pub[:12], e)
        return False


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
                "p=$(wg show wdtt0 allowed-ips 2>/dev/null | "
                f"awk -v ip={shlex.quote(ip)} '$0 ~ ip {{print $1; exit}}'); "
                'if [ -z "$p" ]; then exit 2; fi; wg set wdtt0 peer "$p" remove'
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
    if cell.is_queen or not cell.api_url or not _valid_wg_pub(pub):
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
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.post(
                url,
                headers={"X-Cell-Agent-Secret": secret},
                json={"wg_public_key": pub},
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


async def kick_device_peers(db: AsyncSession, device: Device, *, force: bool = False) -> bool:
    """Remove only this device's known WG key/IP. Never guess GETCONF extras.

    Guessing the newest extra on a cell kicked other paying clients (incident
    2026-08-16). Revoke-while-connected on LTE still needs wdtt-server
    DENIED:no_subscription — do not paper over it by deleting strangers' peers.
    """
    pub = (device.wg_public_key or "").strip()
    addr = device.wg_address or ""
    queen = await get_queen_cell(db)
    on_queen = device.cell_id is None or (queen is not None and device.cell_id == queen.id)
    cell = None if on_queen else (
        await db.get(HiveCell, device.cell_id) if device.cell_id is not None else None
    )

    pubs = [p for p in [pub] if _valid_wg_pub(p)]
    ips = [i for i in [_addr_ip(addr)] if i]
    if not pubs and not ips:
        logger.warning("vpn kick skip device %s — no wg key/address", device.id)
        return False

    ok = False
    if on_queen or cell is None:
        for p in pubs:
            if kick_wg_peer_on_queen(p, force=force):
                ok = True
        for ip in ips:
            if kick_wg_peer_on_queen("", allowed_ip=ip, force=force):
                ok = True
        return ok
    if cell is None:
        return False
    for p in pubs:
        if await kick_wg_peer_on_cell(cell, p):
            ok = True
    for ip in ips:
        if await kick_wg_peer_on_cell(cell, "", allowed_ip=ip):
            ok = True
    return ok


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
        ok = await kick_device_peers(db, device, force=True)
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
    if kicked:
        push_incident(
            source="vpn.kick",
            severity="info",
            message=f"Сняты живые VPN-сессии после отзыва подписки ({kicked})",
            details=user.email,
        )
    return kicked


async def kick_connected_without_subscription(db: AsyncSession) -> int:
    """Sweeper: drop known WG keys of connected devices without a subscription.

    Does not guess GETCONF extras — that removed other clients on the same cell.
    """
    result = await db.execute(
        select(Device).where(
            Device.is_connected == True,  # noqa: E712
            Device.is_active == True,  # noqa: E712
        )
    )
    devices = list(result.scalars().all())
    if not devices:
        return 0
    user_ids = {d.user_id for d in devices}
    users = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(user_ids)))
        ).scalars().all()
    }
    kicked = 0
    for device in devices:
        if (device.device_fingerprint or "").startswith("boot:"):
            continue
        user = users.get(device.user_id)
        if user is None:
            continue
        if await user_has_active_subscription(user, db):
            continue
        if not await kick_device_peers(db, device, force=False):
            continue
        device.is_connected = False
        kicked += 1
    if kicked:
        await db.commit()
        logger.warning("vpn kick sweeper: %s device(s) without subscription", kicked)
    return kicked
