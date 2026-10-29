"""Durable node profiles: reserve, apply on host, publish only verified results.

Legacy ai_exit remains a routing/security role. New profiles do not remove API
standbys, hide servers from old clients, or move devices between nodes.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models import AppSetting, HiveCell
from app.services.hive_slots import cell_name_number

PREFIX = 'node_profiles:'
ROOT = '/opt/silent-vpn/node-profiles'
_tasks: set[asyncio.Task] = set()


def defaults(cell) -> dict:
    return {'ai': bool(getattr(cell, 'ai_exit', False)),
            'gaming': not cell.is_queen and (cell_name_number(cell.name) == 2
                                           or cell.public_ip == '78.17.74.27'),
            'revision': 0, 'state': 'ready', 'error': None}


def decode(cell, value: str | None) -> dict:
    result = defaults(cell)
    if value:
        try:
            data = json.loads(value)
            if (not isinstance(data, dict) or type(data.get('ai')) is not bool
                    or type(data.get('gaming')) is not bool):
                raise ValueError('invalid profile')
            result.update(data)
        except (ValueError, TypeError):
            result.update(state='error', error='Повреждены настройки профилей; примените их повторно')
    result['wg_mtu'] = 1420 if result['gaming'] else 1200
    return result


async def get_profile(db, cell) -> dict:
    row = await db.get(AppSetting, PREFIX + str(cell.id))
    return decode(cell, row.value if row else None)


async def attach_profiles(db, responses: list[dict]) -> list[dict]:
    if not responses:
        return responses
    keys = [PREFIX + str(c['id']) for c in responses]
    rows = (await db.execute(select(AppSetting).where(AppSetting.key.in_(keys)))).scalars().all()
    values = {r.key: r.value for r in rows}
    from types import SimpleNamespace
    for cell in responses:
        cell['profiles'] = decode(SimpleNamespace(**cell), values.get(PREFIX + str(cell['id'])))
    return responses


def _execute(cell, command: str, *, timeout: int = 25) -> str:
    if cell.is_queen:
        # Use the existing helper; never recreate it or touch its peers.
        p = subprocess.run(['docker', 'exec', 'silent-nsenter', 'nsenter', '-t', '1',
                            '-m', '-n', '--', 'sh', '-c', command],
                           capture_output=True, text=True, timeout=timeout)
        if p.returncode:
            raise RuntimeError('Host profile executor failed')
        return p.stdout.strip()
    from app.services.hive_service import resolve_ssh_password
    from app.services.hive_provision_service import _ssh_connect, _run
    password = resolve_ssh_password(cell)
    if not password:
        raise RuntimeError('SSH-пароль сервера не сохранён')
    client = _ssh_connect(cell.public_ip, password, timeout=10)
    try:
        code, out, _ = _run(client, command, timeout=timeout)
        if code:
            raise RuntimeError('Remote profile executor failed')
        return out.strip()
    finally:
        client.close()


def launch(cell, operation_id: str, target: dict) -> None:
    source = Path(__file__).with_name('node_profile_runtime.py').read_bytes()
    filename = 'runtime-' + hashlib.sha256(source).hexdigest()[:16] + '.py'
    request = {**target, 'operation_id': operation_id, 'queen': bool(cell.is_queen),
               'legacy_ai': bool(cell.ai_exit), 'mtu_floor': 1420 if defaults(cell)['gaming'] else 0}
    payload = base64.b64encode(json.dumps({'source': base64.b64encode(source).decode(),
                                         'request': request}).encode()).decode()
    # No secrets in this payload. Only validated UUIDs, booleans and our source.
    program = f'''
import base64,json,os,pathlib,subprocess
p=json.loads(base64.b64decode({payload!r}))
root=pathlib.Path({ROOT!r}); root.mkdir(parents=True,exist_ok=True); os.chmod(root,0o700)
runtime=root/{filename!r}
runtime.write_bytes(base64.b64decode(p['source']))
req=root/{(operation_id + '.request.json')!r}; req.write_text(json.dumps(p['request']))
unit='silent-node-profile-{operation_id}'
subprocess.run(['systemd-run','--quiet','--collect','--unit',unit+'-guard','--on-active=150s',
 '/usr/bin/python3',str(runtime),'recover',{operation_id!r}],check=True)
subprocess.run(['systemd-run','--quiet','--collect','--unit',unit,'--property=RuntimeMaxSec=110s',
 '/usr/bin/python3',str(runtime),'apply',{operation_id!r}],check=True)
'''
    _execute(cell, 'python3 -c ' + shlex.quote(program))


def read_result(cell, operation_id: str) -> dict:
    path = f'{ROOT}/{operation_id}.status.json'
    program = f'''
import json,pathlib,subprocess
p=pathlib.Path({path!r})
if p.exists():
 d=json.loads(p.read_text()); print(json.dumps({{k:d[k] for k in ('state','error','rolled_back','result') if k in d}}))
else:
 s=subprocess.run(['systemctl','show','silent-node-profile-{operation_id}','-p','ActiveState','--value'],capture_output=True,text=True)
 print(json.dumps({{'state':'running' if s.stdout.strip() in ('active','activating') else 'missing'}}))
'''
    return json.loads(_execute(cell, 'python3 -c ' + shlex.quote(program)))


def persist_boot(cell) -> None:
    """Only after verification. Reapply tagged rules at boot without restarting VPN."""
    source = Path(__file__).with_name('node_profile_runtime.py').read_bytes()
    filename = 'runtime-' + hashlib.sha256(source).hexdigest()[:16] + '.py'
    unit = ('[Unit]\nDescription=Silent VPN node profiles\nAfter=network-online.target wdtt.service\n'
            '[Service]\nType=oneshot\nRemainAfterExit=yes\nRestart=on-failure\nRestartSec=10\n'
            f'ExecStart=/usr/bin/python3 {ROOT}/{filename} boot boot\n'
            '[Install]\nWantedBy=multi-user.target\n')
    program = f'''
from pathlib import Path
import subprocess,os
p=Path('/etc/systemd/system/silent-node-profiles.service')
t=p.with_suffix('.tmp'); t.write_text({unit!r}); os.replace(t,p)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','silent-node-profiles.service'],check=True,capture_output=True)
'''
    _execute(cell, 'python3 -c ' + shlex.quote(program))


async def request_change(db, cell, *, ai: bool | None, gaming: bool | None,
                         expected_revision: int | None) -> dict:
    from app.services.hive_service import resolve_ssh_password
    if cell.status not in ('active', 'draining'):
        raise HTTPException(400, 'Профили можно менять только у работающего сервера')
    if not cell.is_queen and not resolve_ssh_password(cell):
        raise HTTPException(400, 'Сохраните SSH-пароль сервера через автоподключение')
    key = PREFIX + str(cell.id)
    await db.execute(insert(AppSetting).values(key=key, value=json.dumps(defaults(cell)))
                     .on_conflict_do_nothing(index_elements=['key']))
    row = (await db.execute(select(AppSetting).where(AppSetting.key == key).with_for_update())).scalar_one()
    current = decode(cell, row.value)
    if current['state'] == 'running':
        raise HTTPException(409, 'Профили этого сервера уже настраиваются. Дождитесь результата')
    if expected_revision is not None and current['revision'] != expected_revision:
        raise HTTPException(409, 'Настройки уже изменены. Обновите страницу и повторите')
    target = {'ai': current['ai'] if ai is None else ai,
              'gaming': current['gaming'] if gaming is None else gaming}
    operation_id = str(uuid.uuid4())
    current.update(state='running', error=None, requested=target, operation_id=operation_id,
                   started_at=datetime.now(timezone.utc).isoformat())
    row.value = json.dumps(current)
    await db.commit()
    # Detach a fully loaded object; never keep DB transactions open across SSH.
    from types import SimpleNamespace
    node = SimpleNamespace(id=cell.id, name=cell.name, public_ip=cell.public_ip,
                           is_queen=cell.is_queen, ai_exit=cell.ai_exit,
                           ssh_password_enc=cell.ssh_password_enc)
    task = asyncio.create_task(_apply_job(node, operation_id, target))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return current


async def _finish(cell, operation_id: str, result: dict) -> None:
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(AppSetting).where(
            AppSetting.key == PREFIX + str(cell.id)).with_for_update())).scalar_one_or_none()
        if not row:
            return
        current = json.loads(row.value)
        if current.get('operation_id') != operation_id or current['state'] != 'running':
            return
        if result['state'] == 'applied':
            if result.get('result') != current['requested']:
                current.update(state='error', error='Результат сервера не совпадает с запросом')
            else:
                current.update(current['requested'])
                current.update(state='ready', revision=current['revision'] + 1, error=None)
        else:
            current.update(state='error', error=result.get('error', 'Не удалось проверить применение профиля'),
                           rolled_back=result.get('rolled_back', False))
        current.pop('requested', None)
        row.value = json.dumps(current)
        await db.commit()


async def _apply_job(cell, operation_id: str, target: dict) -> None:
    try:
        await asyncio.to_thread(launch, cell, operation_id, target)
        for _ in range(80):
            await asyncio.sleep(2)
            result = await asyncio.to_thread(read_result, cell, operation_id)
            if result['state'] in ('applied', 'error'):
                if result['state'] == 'applied':
                    await asyncio.to_thread(persist_boot, cell)
                await _finish(cell, operation_id, result)
                return
        # The host guard owns rollback. Leave the durable operation reserved;
        # recovery can distinguish success from failure even after API restart.
    except Exception:
        # Transport failure is not proof of failure on the host. Reconcile later.
        return


async def recovery_loop() -> None:
    from app.database import AsyncSessionLocal
    while True:
        try:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(select(AppSetting).where(
                    AppSetting.key.startswith(PREFIX, autoescape=True)))).scalars().all()
                pending = []
                for row in rows:
                    try:
                        profile = json.loads(row.value)
                        cell_id = uuid.UUID(row.key[len(PREFIX):])
                        if profile.get('state') == 'running':
                            pending.append((cell_id, profile))
                    except (ValueError, TypeError, AttributeError):
                        continue
                nodes = []
                for cell_id, profile in pending:
                    cell = await db.get(HiveCell, cell_id)
                    if cell:
                        db.expunge(cell)
                        nodes.append((cell, profile))
            for cell, profile in nodes:
                try:
                    result = await asyncio.to_thread(read_result, cell, profile['operation_id'])
                    if result['state'] == 'missing':
                        age = (datetime.now(timezone.utc) - datetime.fromisoformat(profile['started_at'])).total_seconds()
                        if age > 180:
                            result = {'state': 'error', 'error': 'Задача не запустилась на сервере; настройки не подтверждены'}
                    if result['state'] in ('applied', 'error'):
                        if result['state'] == 'applied':
                            await asyncio.to_thread(persist_boot, cell)
                        await _finish(cell, profile['operation_id'], result)
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(10)
