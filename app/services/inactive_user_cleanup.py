"""Opt-in removal of long abandoned accounts; absence of presence must be proven."""
from __future__ import annotations

import asyncio
import calendar
from datetime import datetime, timezone
import json
import shlex

from sqlalchemy import Column, Float, MetaData, Table, Uuid, delete, exists, func, or_, select, update
from app.models import Device, HiveCell, Payment, ReferralReward, Subscription, User, VkHash, VkLinkSession
from app.services.subscription_service import is_user_admin

# Typed separately because the verified-token registry predates ORM models.
_grants = Table('standby_token_grants', MetaData(), Column('user_id', Uuid), Column('seen_at', Float))
BATCH_SIZE = 100


def inactivity_cutoff(now: datetime) -> datetime:
    month_index = now.year * 12 + now.month - 1 - 3
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return now.replace(year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1]))


def _eligible(now):
    from app.config import settings
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL
    cutoff = inactivity_cutoff(now)
    return select(User.id).where(
        User.created_at < cutoff,
        func.coalesce(User.last_seen_at, User.created_at) < cutoff,
        or_(User.vk_linked_at.is_(None), User.vk_linked_at < cutoff),
        User.is_admin.is_(False),
        func.lower(User.email).not_in((settings.ADMIN_LOGIN.lower(), BOOTSTRAP_USER_EMAIL.lower())),
        ~exists(select(Subscription.id).where(Subscription.user_id == User.id,
            Subscription.status == 'active', Subscription.expires_at > now)),
        ~exists(select(Device.id).where(Device.user_id == User.id,
            or_(Device.is_connected.is_(True), Device.last_connected >= cutoff, Device.created_at >= cutoff))),
        ~exists(select(Payment.id).where(Payment.user_id == User.id,
            or_(Payment.status == 'pending', Payment.created_at >= cutoff,
                Payment.completed_at >= cutoff, Payment.manual_activated_at >= cutoff))),
        ~exists(select(_grants.c.user_id).where(_grants.c.user_id == User.id,
            _grants.c.seen_at >= cutoff.replace(tzinfo=timezone.utc).timestamp())),
    )


# Each host's own clock is used, avoiding skew between Queen and cells. Bad JSON,
# failed wg, missing password cache or an unreachable node aborts account removal.
_PRESENCE_PROGRAM = """import json,time,subprocess
from pathlib import Path
now=time.time()
rows=subprocess.run(['wg','show','wdtt0','latest-handshakes'],capture_output=True,text=True,timeout=4,check=True).stdout.splitlines()
pubs=[]
for line in rows:
 parts=line.split()
 if len(parts)!=2:raise ValueError('invalid wg presence')
 age=now-int(parts[1])
 if int(parts[1])>0 and -120<=age<600:pubs.append(parts[0])
devices=json.loads(Path('/etc/wdtt/passwords.json').read_text())['devices']
if not isinstance(devices,dict):raise ValueError('invalid identities')
refs=[str(ref) for ref,d in devices.items() if isinstance(d,dict) and d.get('pub_key') in pubs]
print(json.dumps({'pubs':pubs,'refs':refs,'checked':True}))
"""


def _read_node(host=None, password=None):
    command = 'python3 -c ' + shlex.quote(_PRESENCE_PROGRAM)
    if host is None:
        from app.services.vpn_kick import _nsenter_host
        result = _nsenter_host(command, timeout=12)
        if result.returncode:raise RuntimeError('Queen presence unavailable')
        output = result.stdout.decode() if isinstance(result.stdout, bytes) else result.stdout
    else:
        from app.services.hive_provision_service import _ssh_connect, _run
        if not password:raise RuntimeError('Cell SSH unavailable')
        client = _ssh_connect(host, password, timeout=5)
        try:
            code, output, _ = _run(client, command, timeout=10)
            if code:raise RuntimeError('Cell presence unavailable')
        finally:client.close()
    result = json.loads(output.strip().splitlines()[-1])
    if result.get('checked') is not True or not all(isinstance(result.get(k), list) for k in ('pubs','refs')):
        raise RuntimeError('Invalid presence coverage')
    return result


async def strict_presence(db):
    from app.services.hive_service import resolve_ssh_password
    cells = list((await db.scalars(select(HiveCell).where(HiveCell.is_queen.is_(False)))).all())
    gate = asyncio.Semaphore(2)
    async def read(host=None, password=None):
        async with gate:return await asyncio.to_thread(_read_node, host, password)
    if any(not c.public_ip for c in cells):
        return {'checked':False,'reason':'У одной из сот не указан адрес. Удаление аккаунтов отложено.'}
    rows = await asyncio.gather(read(), *(read(c.public_ip, resolve_ssh_password(c)) for c in cells), return_exceptions=True)
    if any(not isinstance(row, dict) or row.get('checked') is not True for row in rows):
        return {'checked':False, 'reason':'Не удалось проверить живые подключения на всех серверах. Удаление аккаунтов отложено.'}
    return {'checked':True, 'nodes_checked':len(rows),
            'pubs':list({p for row in rows for p in row['pubs']}),
            'refs':list({r for row in rows for r in row['refs']})}


async def preview_inactive_users(db, *, now=None):
    now = now or datetime.utcnow()
    eligible = _eligible(now).subquery()
    count = await db.scalar(select(func.count()).select_from(eligible))
    devices = await db.scalar(select(func.count(Device.id)).where(Device.user_id.in_(select(eligible.c.id))))
    return {'candidate_users':count, 'candidate_devices':devices,
            'cutoff':inactivity_cutoff(now).isoformat(timespec='seconds')+'Z',
            'batch_limit':BATCH_SIZE,
            'note':'Предварительная выборка. Действующие подписки, администраторы, недавняя активность и платежи защищены. Перед удалением повторно проверяются подключения на всех серверах.'}


async def delete_inactive_users(db, *, now=None):
    from app.services.session_presence import online_flags
    from app.services.vpn_deny_net import remember_deleted_device_ids
    now = now or datetime.utcnow()
    presence = await strict_presence(db)
    if not presence.get('checked'):
        return {'deleted_users':0, 'deleted_devices':0, 'skipped':True, 'reason':presence['reason']}
    # Lock parent rows before rechecking subscriptions/activity. FK writers (new
    # device/subscription/payment) cannot race the final parent deletion.
    users = list((await db.scalars(select(User).where(User.id.in_(_eligible(now)))
        .order_by(User.created_at, User.id).limit(BATCH_SIZE).with_for_update(of=User, skip_locked=True))).all())
    ids = [u.id for u in users if not is_user_admin(u)]
    if not ids:return {'deleted_users':0, 'deleted_devices':0, 'nodes_checked':presence['nodes_checked']}
    devices = list((await db.scalars(select(Device).where(Device.user_id.in_(ids)).with_for_update())).all())
    flags = online_flags(devices, presence)
    live_users = {d.user_id for d in devices if flags[str(d.id)]}
    # Fresh statement after acquiring locks sees activity/payment transactions
    # that completed while we waited for the locks.
    rechecked = set((await db.scalars(_eligible(now).where(User.id.in_(ids)))).all())
    ids = [uid for uid in ids if uid in rechecked and uid not in live_users]
    owned = [d.id for d in devices if d.user_id in ids]
    if ids:
        await remember_deleted_device_ids(db, owned)
        for model in (VkHash, VkLinkSession, Device, Payment, Subscription):
            await db.execute(delete(model).where(model.user_id.in_(ids)).execution_options(synchronize_session=False))
        await db.execute(delete(ReferralReward).where(or_(ReferralReward.inviter_id.in_(ids), ReferralReward.invitee_id.in_(ids))))
        await db.execute(update(User).where(User.referred_by_user_id.in_(ids)).values(referred_by_user_id=None))
        await db.execute(delete(_grants).where(_grants.c.user_id.in_(ids)))
        await db.execute(delete(User).where(User.id.in_(ids)).execution_options(synchronize_session=False))
    return {'deleted_users':len(ids), 'deleted_devices':len(owned), 'protected_live_users':len(live_users),
            'nodes_checked':presence['nodes_checked'], 'batch_limit':BATCH_SIZE,
            'cutoff':inactivity_cutoff(now).isoformat(timespec='seconds')+'Z'}
