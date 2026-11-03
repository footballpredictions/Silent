#!/usr/bin/env python3
"""Host-only cleaner. Standard library, bounded operations, no VPN/Docker restarts."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

API='http://127.0.0.1:8000/api/vpn/internal/vps-cleanup'
ENV_PATH=Path('/opt/silent-vpn/backend/.env')
LOCK_PATH=Path('/run/lock/silent-vps-cleanup.lock')


def internal_secret(path=ENV_PATH):
    for line in path.read_text(encoding='utf-8').splitlines():
        key,sep,value=line.partition('=')
        if sep and key.strip()=='INTERNAL_API_SECRET':
            value=value.strip()
            if len(value)>1 and value[0] in ('"',"'") and value[-1]==value[0]:return value[1:-1]
            return value.split(' #',1)[0].strip()
    raise RuntimeError('INTERNAL_API_SECRET не настроен')


def api_request(path, body=None, *, timeout=15):
    token=internal_secret()
    if not token:raise RuntimeError('INTERNAL_API_SECRET пуст')
    request=urllib.request.Request(API+path,
        data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
        headers={'X-Internal-Secret':token,'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=timeout) as response:return json.load(response)


def command(args, *, timeout=60):
    name=args[0]
    if not shutil.which(name):return {'status':'skipped','reason':'Команда не установлена'}
    try:
        process=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
        if process.returncode:return {'status':'error','error':(process.stderr or process.stdout or 'Команда завершилась с ошибкой')[-300:]}
        return {'status':'ok'}
    except (OSError,subprocess.TimeoutExpired):return {'status':'error','error':'Не удалось завершить операцию за отведённое время'}


def clean_old_deploy_files(root=Path('/tmp'), *, now=None):
    now=time.time() if now is None else now
    count=0
    root=root.resolve()
    prefixes=('deploy_','fix_','install_','remove_','silent_','check_','hotfix_')
    for path in list(root.iterdir())[:5000]:
        if not path.name.startswith(prefixes) or path.suffix not in ('.sh','.py'):continue
        try:
            if path.is_symlink() or not path.is_file() or path.resolve().parent!=root:continue
            stat=path.stat()
            if stat.st_uid!=0 or now-stat.st_mtime<7*86400:continue
            if path.stat().st_ino!=stat.st_ino:continue
            path.unlink();count+=1
        except OSError:continue
    return count


def clean_disk(journal_mb):
    journal_mb=max(50,min(2000,int(journal_mb)))
    before=shutil.disk_usage('/').free
    steps=[]
    operations=[('journal_rotate',['journalctl','--rotate']),
                ('journal',['journalctl',f'--vacuum-size={journal_mb}M']),
                ('apt_cache',['apt-get','clean']),
                ('docker_images',['docker','image','prune','-f','--filter','until=168h']),
                ('docker_cache',['docker','builder','prune','-f','--filter','until=168h'])]
    for name,args in operations:steps.append({'name':name,**command(args)})
    try:steps.append({'name':'old_deploy_files','status':'ok','deleted':clean_old_deploy_files()})
    except OSError:steps.append({'name':'old_deploy_files','status':'error','error':'Не удалось проверить временные deploy-файлы'})
    after=shutil.disk_usage('/').free
    return {'freed_approx_mb':max(0,round((after-before)/1024**2,1)),
            'available_mb':round(after/1024**2,1),'journal_max_mb':journal_mb,'steps':steps}


def run_job(api=api_request, cleaner=clean_disk):
    job=api('/claim',{})
    if not job.get('run'):return {'status':'idle','reason':job.get('reason')}
    run_id=job['run_id']
    result={}
    error=None
    try:
        result=cleaner(job['journal_max_mb'])
        if job.get('inactive_users_enabled'):
            result['users']=api('/inactive-users',{'run_id':run_id},timeout=180)
        failed=any(step['status']=='error' for step in result.get('steps',[]))
        deferred=bool(result.get('users',{}).get('skipped'))
        status='partial' if failed or deferred else 'succeeded'
        if failed:error='Некоторые операции очистки завершились с ошибкой. Подробности сохранены в результате.'
        if deferred:error=result['users'].get('reason','Удаление аккаунтов отложено: проверка подключений не завершена.')
    except Exception as exc:
        status='failed';error=f'Очистка не завершена ({type(exc).__name__}). Повторите запуск.'
    summary=f"Освобождено примерно {result.get('freed_approx_mb',0)} МБ."
    if 'users' in result:summary+=f" Удалено аккаунтов: {result['users'].get('deleted_users',0)}."
    if status!='succeeded':summary+=' Есть ошибки или отложенные операции.'
    body={'run_id':run_id,'status':status,'summary':summary,'result':result,'error':error}
    api('/meta',body)
    return body


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disk-only',action='store_true')
    parser.add_argument('--journal-mb',type=int,default=200)
    args=parser.parse_args()
    import fcntl
    os.umask(0o077)
    LOCK_PATH.parent.mkdir(parents=True,exist_ok=True)
    with LOCK_PATH.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status':'busy'}));return
        result=clean_disk(args.journal_mb) if args.disk_only else run_job()
        print(json.dumps(result,ensure_ascii=False))
        if result.get('status')=='failed':raise SystemExit(1)


if __name__=='__main__':main()
