"""Bounded offline user authentication/config API. Contains no Queen signing key."""
from __future__ import annotations

from collections import OrderedDict
import asyncio
from hashlib import sha256
import json
import re
from pathlib import Path
import threading
import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

KEY_PATH = Path('/etc/wdtt/standby_api.key')
MAX_SNAPSHOT_AGE = 3600


class OfflineSnapshot:
    def __init__(self, loader, key_loader=None, clock=time.time):
        self.loader = loader
        self.key_loader = key_loader or KEY_PATH.read_bytes
        self.clock = clock
        self._cache = None
        self._encrypted = None
        self._lock = threading.RLock()
        self._attempts = OrderedDict()
        self._password_gate = threading.BoundedSemaphore(2)
        self._selection = OrderedDict()

    def read(self):
        manifest = self.loader() or {}
        envelope = manifest.get('offline_api') or {}
        encrypted = envelope.get('ciphertext')
        if not isinstance(encrypted, str) or len(encrypted) > 32*1024*1024:
            raise HTTPException(503, 'Резервный снимок авторизации ещё не готов')
        now = self.clock()
        with self._lock:
            if encrypted != self._encrypted:
                try:
                    key = self.key_loader().strip()
                    raw = Fernet(key).decrypt_at_time(encrypted.encode(), ttl=MAX_SNAPSHOT_AGE+60, current_time=int(now))
                    data = json.loads(raw)
                    if data.get('schema') != 1 or data.get('cell_id') != manifest.get('cell_id'):
                        raise ValueError('snapshot binding')
                except (OSError, InvalidToken, ValueError, TypeError, json.JSONDecodeError):
                    raise HTTPException(503, 'Резервный снимок авторизации недоступен')
                self._cache, self._encrypted = data, encrypted
            data = self._cache
            try:
                issued, until = float(data['issued_at']), float(data['valid_until'])
                if not issued-60 <= now < until or until-issued > MAX_SNAPSHOT_AGE:
                    raise ValueError('stale snapshot')
            except (ValueError, KeyError, TypeError):
                raise HTTPException(503, 'Резервный снимок устарел; ожидается связь с Ульем')
            return data

    def authorize(self, bearer: str, kind='access'):
        data = self.read()
        digest = sha256(bearer.encode()).hexdigest()
        grant = data.get('grants', {}).get(digest)
        if not grant or grant.get('type') != kind or float(grant.get('exp', 0)) <= self.clock():
            # A valid legacy token may not have been observed before the outage.
            # Do not turn this into 401 and log a working old client out.
            raise HTTPException(503, 'Этот сеанс ещё не сохранён на резервном сервере')
        user = data.get('users', {}).get(grant.get('user_id'))
        if not user or not user.get('active') or not user.get('verified'):
            raise HTTPException(403, 'Доступ к аккаунту недоступен')
        return data, user

    def login(self, email: str, password: str, fingerprint: str, peer: str):
        import bcrypt
        data = self.read()
        email = email.strip().lower()
        now = self.clock()
        with self._lock:
            for rate_key, limit in [((peer,email),10),((peer,'*'),30)]:
                times = [t for t in self._attempts.get(rate_key, ()) if now-t < 60]
                if len(times) >= limit:
                    raise HTTPException(429, 'Слишком много попыток входа. Повторите позже.')
                self._attempts[rate_key] = times+[now]
                self._attempts.move_to_end(rate_key)
            while len(self._attempts) > 2048:
                self._attempts.popitem(last=False)
        user = next((u for u in data.get('users', {}).values() if u.get('email') == email), None)
        # Fixed valid dummy verifier avoids a cheap unknown-account timing oracle.
        encoded = user.get('password_hash') if user else None
        dummy = '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxgFvBWkKCMFiKjZHOXTl6Uge7S'
        if not self._password_gate.acquire(blocking=False):
            raise HTTPException(429, 'Повторите вход через несколько секунд')
        try:
            checked = bcrypt.checkpw(password.encode()[:72], (encoded or dummy).encode())
            valid = bool(encoded) and checked
        except (ValueError, TypeError):
            valid = False
        finally:
            self._password_gate.release()
        if not valid:
            raise HTTPException(401, 'Неверный email или пароль')
        if not user.get('active') or not user.get('verified'):
            raise HTTPException(403, 'Аккаунт недоступен или email не подтверждён')
        if fingerprint and not any(d.get('user_id') == user['id'] and d.get('fingerprint') == fingerprint
                                   and d.get('active') for d in data.get('devices', {}).values()):
            raise HTTPException(503, 'Новое устройство можно зарегистрировать после восстановления Улья')
        return user['tokens']

    def device(self, data, user, fingerprint):
        for device in data.get('devices', {}).values():
            if device.get('user_id') == user['id'] and device.get('fingerprint') == fingerprint:
                if not device.get('active'):
                    raise HTTPException(403, 'Сеанс устройства отключён')
                return device
        raise HTTPException(503, 'Устройство ещё не сохранено в резервном снимке')

    def node(self, data, user, slot, version=''):
        node = data.get('servers', {}).get(slot)
        if not node or node.get('status') not in ('active', 'draining'):
            raise HTTPException(503, 'Выбранный сервер сейчас недоступен')
        if node.get('admin_only') and not user.get('is_admin'):
            raise HTTPException(403, 'Сервер временно доступен только администратору')
        parts = [int(x) for x in re.findall(r'\d+', version)[:3]]
        parts += [0]*(3-len(parts))
        if node.get('ai_exit') and tuple(parts) < (1,0,165):
            raise HTTPException(403, 'Сервер доступен начиная с версии 1.0.165')
        return node

    def config(self, data, user, device, slot, version=''):
        if not user.get('vpn_allowed'):
            raise HTTPException(403, 'Для подключения нужна активная подписка')
        until = user.get('subscription_until')
        if until and float(until) <= self.clock():
            raise HTTPException(403, 'Срок подписки истёк')
        node = self.node(data,user,slot,version)
        if not all(device.get(k) for k in ('wg_private_key','wg_address','wdtt_password')) or not user.get('vk_hashes'):
            raise HTTPException(503, 'Полная конфигурация ещё не сохранена на резервном сервере')
        return {
            'device_id':device['id'], 'wg_private_key':device['wg_private_key'],
            'wg_address':device['wg_address'], 'wg_dns':node['wg_dns'],
            'server_ip':node['public_ip'], 'server_port':node['wdtt_port'],
            'server_public_key':node['wg_public_key'], 'wdtt_password':device['wdtt_password'],
            'vk_hashes':user['vk_hashes'], 'stream_count':user['stream_count'],
            'selected_server':slot, 'wg_mtu':node['wg_mtu'],
            # Do not overwrite live profile/online counters with an older snapshot.
            'client_sync':{'theme':data.get('theme'), 'hashes':user['vk_hashes']},
        }

    def selected(self, data, device, requested=''):
        with self._lock:
            selected = self._selection.get(device['id'])
        value = requested or (selected[0] if selected and selected[1]>self.clock() else '') or device.get('preferred_server')
        if value in ('queen',None,''):
            return 'server1'
        return value

    def servers(self, data, user, selected, version):
        result=[]
        for slot,node in sorted(data.get('servers',{}).items(),key=lambda item:int(item[0].removeprefix('server'))):
            try:self.node(data,user,slot,version)
            except HTTPException:continue
            result.append({'key':slot,'title':node['name'],'public_ip':node['public_ip'],
                           'wdtt_port':node['wdtt_port'],'online_count':0,
                           'api_base':node.get('api_url','')})
        return {'selected_server':selected,'servers':result}

    async def respond(self, request, rest):
        """Read/recover existing sessions only. Never touch WG, DNAT or passwords.json."""
        path = rest.strip('/')
        method = request.method
        body = {}
        if method=='POST':
            raw = await request.body()
            if len(raw)>32768:
                raise HTTPException(413,'Запрос слишком большой')
            try:body=json.loads(raw)
            except (ValueError,UnicodeError):raise HTTPException(422,'Некорректный JSON')
            if not isinstance(body,dict):raise HTTPException(422,'Ожидается объект JSON')
        if method=='POST' and path=='auth/login':
            email,password=body.get('email',''),body.get('password','')
            device=body.get('device') or {}
            if not isinstance(email,str) or not isinstance(password,str) or len(email)>320 or len(password)>1024 or not isinstance(device,dict):
                raise HTTPException(422,'Некорректные данные входа')
            fingerprint=device.get('device_fingerprint','')
            if not isinstance(fingerprint,str) or len(fingerprint)>255:raise HTTPException(422,'Некорректное устройство')
            peer=request.client.host if request.client else 'unknown'
            return await asyncio.to_thread(self.login,email,password,fingerprint,peer)
        if method=='POST' and path=='auth/refresh':
            token=body.get('refresh_token','')
            if not isinstance(token,str):raise HTTPException(422,'Некорректный токен')
            data,user=self.authorize(token,'refresh')
            # Preserve the already-authorized refresh credential: legacy clients
            # can resume an ordinary session when the Queen returns, without logout.
            return {**user['tokens'],'refresh_token':token}
        supported_get={'vpn/config','vpn/servers','vpn/hashes','users/me'}
        supported_post={'vpn/device/register','vpn/servers/select','vpn/connect','vpn/disconnect'}
        if not ((method=='GET' and path in supported_get) or (method=='POST' and path in supported_post)):
            raise HTTPException(503,'Для этого действия нужно восстановление связи с Ульем')
        header=request.headers.get('authorization','')
        if not header.lower().startswith('bearer '):raise HTTPException(503,'Для восстановления нужен сохранённый сеанс')
        data,user=self.authorize(header[7:].strip())
        if path=='users/me':return user['profile']
        if path=='vpn/hashes':
            hashes=user['vk_hashes']
            return {'hashes':hashes,'bootstrap_hash':user.get('bootstrap_hash',''),
                    'mode':'full' if len(hashes)>1 else 'bootstrap','items':user.get('hash_items',[])}
        fingerprint=request.query_params.get('fingerprint','') if method=='GET' else body.get('device_fingerprint','')
        if not isinstance(fingerprint,str) or len(fingerprint)>255:raise HTTPException(422,'Некорректное устройство')
        device=self.device(data,user,fingerprint)
        requested=request.query_params.get('preferred_server','') if method=='GET' else body.get('preferred_server','')
        if not isinstance(requested,str) or len(requested)>32:raise HTTPException(422,'Некорректный сервер')
        slot=self.selected(data,device,requested)
        version=request.query_params.get('app_version','') or request.headers.get('x-app-version','') or body.get('app_version','') or ''
        if not isinstance(version,str) or len(version)>128:raise HTTPException(422,'Некорректная версия')
        if path=='vpn/disconnect':return {'status':'disconnected'}
        if path=='vpn/servers':return self.servers(data,user,slot,version)
        config=self.config(data,user,device,slot,version)
        if path=='vpn/servers/select':
            with self._lock:
                self._selection[device['id']]=(slot,data['valid_until'])
                self._selection.move_to_end(device['id'])
                while len(self._selection)>4096:self._selection.popitem(last=False)
            return self.servers(data,user,slot,version)
        if path=='vpn/connect':return {'status':'connected','mode':'full'}
        return config
