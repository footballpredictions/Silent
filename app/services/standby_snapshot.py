"""Encrypted recovery snapshots for known accounts/devices; no global JWT key export."""
from __future__ import annotations

from collections import defaultdict
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import time

from cryptography.fernet import Fernet, InvalidToken
from jose import jwt
from sqlalchemy import select, text

from app.config import settings
from app.core.security import decrypt_value
from app.models import AppSetting, Device, HiveCell, Subscription, User, VkHash

ENABLED_KEY = 'standby_offline_cells_v1'
KEY_PREFIX = 'standby_offline_key_v1:'
MAX_AGE = 3600
_common_cache: dict | None = None
_common_until = 0.0
_common_lock: asyncio.Lock | None = None
_envelopes: dict[str, tuple] = {}


def invalidate_snapshot_cache():
    global _common_until
    _common_until = 0.0


async def cached_common(db):
    global _common_cache, _common_until, _common_lock
    if _common_cache is not None and time.monotonic() < _common_until:
        return _common_cache
    if _common_lock is None:
        _common_lock = asyncio.Lock()
    async with _common_lock:
        if _common_cache is None or time.monotonic() >= _common_until:
            _common_cache = await build_common(db)
            _common_until = time.monotonic()+60
        return _common_cache


def recovery_tokens(user_id, until: int) -> dict:
    common = {'sub':str(user_id), 'exp':int(until), 'standby_until':int(until),
              'standby_scope':'vpn-recovery-v1'}
    return {
        'access_token':jwt.encode({**common,'type':'access'},settings.JWT_SECRET,algorithm=settings.JWT_ALGORITHM),
        'refresh_token':jwt.encode({**common,'type':'refresh'},settings.JWT_SECRET,algorithm=settings.JWT_ALGORITHM),
        'token_type':'bearer',
    }


async def enabled_cells(db) -> set[str]:
    row = await db.get(AppSetting, ENABLED_KEY)
    try:
        value = json.loads(row.value) if row else []
        return {str(x) for x in value} if isinstance(value, list) else set()
    except (TypeError, ValueError):
        return set()


async def cell_key(db, cell_id) -> bytes | None:
    row = await db.get(AppSetting, KEY_PREFIX+str(cell_id))
    if row is None:
        return None
    try:
        key = decrypt_value(row.value).encode('ascii')
        Fernet(key)
        return key
    except (ValueError, TypeError, UnicodeError, InvalidToken):
        return None


def _timestamp(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).timestamp()


async def build_common(db) -> dict:
    """Read only. Do not call config builders that move devices or alter WG peers."""
    from app.services.hive_slots import slot_for_cell, cell_slot_title
    from app.services.hive_profiles import get_profile
    from app.services.threat_filter_settings import resolve_wg_dns
    from app.services.subscription_service import is_user_admin, is_test_user, is_test_mode_excluded, effective_device_limit, TEST_PLAN
    from app.services.test_mode_settings import is_registration_test_mode_enabled
    from app.services.theme_settings import load_theme
    from app.services.vpn_service import BOOTSTRAP_USER_EMAIL

    now = int(time.time())
    until = now+MAX_AGE
    users = list((await db.execute(select(User).where(User.email != BOOTSTRAP_USER_EMAIL))).scalars())
    devices = list((await db.execute(select(Device))).scalars())
    subscriptions = list((await db.execute(select(Subscription).where(Subscription.status=='active'))).scalars())
    hashes = (await db.execute(select(VkHash.user_id,VkHash.hash_value,VkHash.slot_index).where(VkHash.is_active==True).order_by(VkHash.slot_index))).all()
    hash_map = defaultdict(list)
    item_map = defaultdict(list)
    for uid, value, slot_index in hashes:
        value = (value or '').strip()
        if value and value not in hash_map[uid] and len(hash_map[uid]) < 4:
            hash_map[uid].append(value)
            item_map[uid].append({'hash':value,'label':f'Сервер #{slot_index}','source':'server',
                                  'slot_index':slot_index,'is_active':True,'status':'active'})
    sub_map = defaultdict(list)
    for sub in subscriptions:
        if sub.is_active:
            sub_map[sub.user_id].append(sub)
    device_map = defaultdict(list)
    global_test = await is_registration_test_mode_enabled(db)
    for device in devices:
        if not device.device_fingerprint.startswith('boot:'):
            device_map[device.user_id].append(device)

    published = {}
    grants = {}
    for user in users:
        if not device_map.get(user.id):
            continue
        uid = str(user.id)
        admin = is_user_admin(user)
        test = not admin and (is_test_user(user) or (global_test and not is_test_mode_excluded(user)))
        live = sorted([s for s in sub_map.get(user.id, []) if test or s.plan_type != TEST_PLAN], key=lambda x:x.expires_at, reverse=True)
        sub = live[0] if live else None
        allowed = bool(user.is_active and user.is_verified and (admin or test or sub))
        sub_until = None if admin or test else _timestamp(sub.expires_at) if sub else None
        user_hashes = list(dict.fromkeys(([user.bootstrap_hash.strip()] if user.bootstrap_hash else []) + hash_map.get(user.id, [])))
        owned = [d for d in device_map[user.id] if d.is_active]
        subscription = {'is_active':allowed, 'plan_type':'unlimited' if admin else 'test' if test else sub.plan_type if sub else None,
                        'expires_at':None if admin or test or sub is None else sub.expires_at.isoformat(),
                        'days_left':9999 if admin or test else sub.days_left if sub else 0}
        profile = {'id':uid,'email':user.email,'display_id':user.display_id,'is_admin':admin,
                   'subscription':subscription,'devices_count':len(owned),'connected_count':sum(bool(d.is_connected) for d in owned),
                   'max_devices':effective_device_limit(user,sub.plan_type if sub else None),'vk_linked':user.vk_user_id is not None,
                   'devices':[{'id':str(d.id),'device_name':d.device_name,'device_type':d.device_type,
                               'is_connected':bool(d.is_connected),'last_connected':d.last_connected.isoformat() if d.last_connected else None} for d in owned]}
        tokens = recovery_tokens(uid, until)
        boot = (user.bootstrap_hash or '').strip()
        items = ([{'hash':boot,'label':'Bootstrap','source':'bootstrap','slot_index':None,
                   'is_active':True,'status':'active'}] if boot else []) + item_map.get(user.id,[])
        published[uid] = {'id':uid,'email':user.email.strip().lower(),'active':bool(user.is_active),
                          'verified':bool(user.is_verified),'is_admin':admin,'password_hash':user.password_hash,
                          'vpn_allowed':allowed,'subscription_until':sub_until,
                          'vk_hashes':user_hashes,'stream_count':9,
                          'bootstrap_hash':boot,'hash_items':items,
                          'profile':profile,'tokens':tokens}
        for field, kind in [('access_token','access'),('refresh_token','refresh')]:
            grants[sha256(tokens[field].encode()).hexdigest()] = {'user_id':uid,'type':kind,'exp':until}

    # Legacy clients keep their current bearer tokens. This registry contains
    # only digests captured after successful main-server verification.
    rows = (await db.execute(text('SELECT token_hash,user_id,token_type,expires_at FROM standby_token_grants WHERE expires_at>:now AND seen_at>:since ORDER BY seen_at DESC LIMIT 20000'),
                             {'now':now,'since':now-7*86400})).mappings()
    for row in rows:
        uid = str(row['user_id'])
        if uid in published:
            grants[row['token_hash']] = {'user_id':uid,'type':row['token_type'],'exp':row['expires_at']}

    known_devices = {}
    for device in devices:
        uid = str(device.user_id)
        if uid not in published:
            continue
        private = ''
        if device.wg_private_key_enc:
            try:
                private = decrypt_value(device.wg_private_key_enc)
            except Exception:
                pass
        known_devices[str(device.id)] = {
            'id':str(device.id),'user_id':uid,'fingerprint':device.device_fingerprint,
            'active':bool(device.is_active),'wg_private_key':private,'wg_public_key':device.wg_public_key or '',
            'wg_address':device.wg_address or '',
            'wdtt_password':(settings.WDTT_MASTER_PASSWORD or device.wdtt_password or '').strip(),
            'preferred_server':device.preferred_server or 'server1',
        }
    servers = {}
    dns = await resolve_wg_dns(db)
    cells = list((await db.execute(select(HiveCell).where(HiveCell.status.in_(('active','draining'))))).scalars())
    for cell in cells:
        slot = slot_for_cell(cell)
        if not slot or not cell.wg_public_key:
            continue
        policy = await get_profile(db,cell)
        servers[slot] = {'id':str(cell.id),'public_ip':cell.public_ip,'wg_public_key':cell.wg_public_key,
                         'wdtt_port':int(cell.wdtt_port or settings.VPN_SERVER_PORT),
                         'wg_mtu':policy['wg_mtu'],'wg_dns':'1.1.1.1,1.0.0.1' if policy['ai'] and dns=='77.88.8.8,77.88.8.1' else dns,
                         'api_url':cell.api_url,'admin_only':bool(getattr(cell,'admin_only',False)),
                         'ai_exit':bool(cell.ai_exit and not cell.is_queen),'status':cell.status,'name':cell_slot_title(cell,slot)}
    theme = await load_theme(db,persist_migration=False)
    return {'schema':1,'issued_at':now,'valid_until':until,'users':published,'devices':known_devices,
            'grants':grants,'servers':servers,'theme':theme.model_dump(mode='json')}


async def encrypt_for_cell(db, cell, common: dict | None = None) -> dict | None:
    if str(cell.id) not in await enabled_cells(db):
        return None
    if common == {}:
        return None
    key = await cell_key(db,cell.id)
    if key is None:
        return None
    common = common if common is not None else await cached_common(db)
    saved = _envelopes.get(str(cell.id))
    if saved and saved[0] is common and saved[1] == key:
        return saved[2]
    data = dict(common)
    data['cell_id'] = str(cell.id)
    raw = json.dumps(data,ensure_ascii=True,separators=(',',':')).encode()
    envelope = {'schema':1,'ciphertext':Fernet(key).encrypt(raw).decode()}
    _envelopes[str(cell.id)] = (common,key,envelope)
    return envelope
