"""Cleanup settings and a durable, single-consumer host job (no VPN restarts)."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import asyncio
import json
import logging
import uuid
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import AppSetting

ENABLED_KEY='vps_cleanup_enabled'
INTERVAL_DAYS_KEY='vps_cleanup_interval_days'
JOURNAL_MB_KEY='vps_cleanup_journal_mb'
RUN_NOW_KEY='vps_cleanup_run_now'
LAST_RUN_AT_KEY='vps_cleanup_last_run_at'
LAST_SUMMARY_KEY='vps_cleanup_last_summary'
INACTIVE_USERS_KEY='vps_cleanup_inactive_users'
JOB_KEY='vps_cleanup_job_v1'
DEFAULT_INTERVAL_DAYS=7
DEFAULT_JOURNAL_MB=200


def _truthy(value):return bool(value) and value.strip().lower() in ('true','1','yes','on')
def _now():return datetime.now(timezone.utc)
def _iso(value=None):return (value or _now()).isoformat(timespec='seconds').replace('+00:00','Z')
def _date(value):
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (AttributeError,ValueError,TypeError):return None
def _clamp_int(raw, default, lo, hi):
    try:return max(lo,min(hi,int(str(raw).strip())))
    except (TypeError,ValueError):return default


async def _set_setting(db,key,value):
    row=await db.get(AppSetting,key)
    if row is None:db.add(AppSetting(key=key,value=value))
    else:row.value=value


async def _values(db):
    keys=[ENABLED_KEY,INTERVAL_DAYS_KEY,JOURNAL_MB_KEY,RUN_NOW_KEY,LAST_RUN_AT_KEY,LAST_SUMMARY_KEY,INACTIVE_USERS_KEY,JOB_KEY]
    return {r.key:r.value for r in (await db.execute(select(AppSetting).where(AppSetting.key.in_(keys)))).scalars()}


def _job(raw):
    try:
        value=json.loads(raw or '{}')
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):return {}


async def _locked_job(db):
    await db.execute(text("INSERT INTO app_settings(key,value) VALUES(:key,'{}') ON CONFLICT(key) DO NOTHING"),{'key':JOB_KEY})
    row=await db.scalar(select(AppSetting).where(AppSetting.key==JOB_KEY).with_for_update())
    return row,_job(row.value)


def _store(row,job):row.value=json.dumps(job,ensure_ascii=False,separators=(',',':'))


async def get_vps_cleanup_status(db: AsyncSession) -> dict:
    values=await _values(db)
    job=_job(values.get(JOB_KEY))
    state=job.get('status','idle')
    error=job.get('error') or None
    queued_at=_date(job.get('requested_at'))
    if state=='queued' and queued_at and (_now()-queued_at).total_seconds()>90:
        error='Исполнитель ещё не подтвердил запуск. Таймер повторит попытку автоматически.'
    return {'enabled':_truthy(values.get(ENABLED_KEY)),
        'interval_days':_clamp_int(values.get(INTERVAL_DAYS_KEY),7,1,30),
        'journal_max_mb':_clamp_int(values.get(JOURNAL_MB_KEY),200,50,2000),
        'inactive_users_enabled':_truthy(values.get(INACTIVE_USERS_KEY)),
        'run_now':_truthy(values.get(RUN_NOW_KEY)),
        'run_id':job.get('id'),'status':state,
        'started_at':job.get('started_at'),'finished_at':job.get('finished_at'),
        'last_run_at':values.get(LAST_RUN_AT_KEY) or None,
        'last_summary':values.get(LAST_SUMMARY_KEY) or None,
        'error':error,'result':job.get('result') or {},
        'note':'Тома Docker, действующие контейнеры, файлы OTA и работающие VPN не затрагиваются. Удаление неактивных аккаунтов включается отдельно.'}


async def set_vps_cleanup(db: AsyncSession, *, enabled: bool, interval_days=None,
                          journal_max_mb=None, run_now=None, inactive_users_enabled=None) -> dict:
    row,job=await _locked_job(db)
    values=await _values(db)
    was_enabled=_truthy(values.get(ENABLED_KEY))
    await _set_setting(db,ENABLED_KEY,'true' if enabled else 'false')
    if interval_days is not None:await _set_setting(db,INTERVAL_DAYS_KEY,str(_clamp_int(interval_days,7,1,30)))
    if journal_max_mb is not None:await _set_setting(db,JOURNAL_MB_KEY,str(_clamp_int(journal_max_mb,200,50,2000)))
    if inactive_users_enabled is not None:await _set_setting(db,INACTIVE_USERS_KEY,'true' if inactive_users_enabled else 'false')
    request=run_now is True or (enabled and not was_enabled and run_now is None)
    if request and job.get('status') not in ('queued','running'):
        job={'id':str(uuid.uuid4()),'status':'queued','requested_at':_iso()}
        _store(row,job)
        await _set_setting(db,RUN_NOW_KEY,'true')
    elif not enabled and run_now is not True and job.get('status')!='running':
        await _set_setting(db,RUN_NOW_KEY,'false')
        if job.get('status')=='queued':
            job['status']='idle';_store(row,job)
    await db.commit()
    return await get_vps_cleanup_status(db)


async def get_vps_cleanup_host_payload(db):return await get_vps_cleanup_status(db)


async def claim_vps_cleanup(db):
    row,job=await _locked_job(db)
    now=_now()
    if job.get('status')=='running':
        started=_date(job.get('started_at'))
        if started and now-started<timedelta(minutes=15):
            await db.commit();return {'run':False,'reason':'already_running'}
        job.update(status='failed',error='Предыдущий исполнитель не завершил очистку.',finished_at=_iso())
        _store(row,job)
    values=await _values(db)
    manual=_truthy(values.get(RUN_NOW_KEY)) and job.get('status')=='queued'
    last=_date(values.get(LAST_RUN_AT_KEY))
    due=not last or now-last>=timedelta(days=_clamp_int(values.get(INTERVAL_DAYS_KEY),7,1,30))
    if job.get('status')=='failed' and _date(job.get('finished_at')):
        due=now-_date(job['finished_at'])>=timedelta(hours=1)
    if not manual and (not _truthy(values.get(ENABLED_KEY)) or not due):
        await db.commit();return {'run':False,'reason':'not_due'}
    config={'journal_max_mb':_clamp_int(values.get(JOURNAL_MB_KEY),200,50,2000),
            'inactive_users_enabled':_truthy(values.get(INACTIVE_USERS_KEY))}
    job={'id':job['id'] if manual else str(uuid.uuid4()),'status':'running',
         'requested_at':job.get('requested_at') if manual else _iso(),
         'started_at':_iso(),'config':config}
    _store(row,job)
    await _set_setting(db,RUN_NOW_KEY,'false')
    await db.commit()
    return {'run':True,'run_id':job['id'],**config}


async def cleanup_inactive_users_for_job(db, run_id):
    from fastapi import HTTPException
    row,job=await _locked_job(db)
    if job.get('id')!=run_id or job.get('status')!='running':
        raise HTTPException(409,'Запуск очистки уже неактуален')
    if not job.get('config',{}).get('inactive_users_enabled'):
        raise HTTPException(403,'Удаление неактивных аккаунтов выключено')
    if job.get('users_done'):
        await db.commit();return job['users_result']
    from app.services.inactive_user_cleanup import delete_inactive_users
    result=await delete_inactive_users(db)
    job.update(users_done=True,users_result=result)
    _store(row,job)
    await db.commit()
    if result.get('deleted_users'):
        from app.services.hive_cell_sync import invalidate_manifest_cache,sync_all_cell_manifests
        from app.services.vpn_kick import sync_unpaid_deny_net
        from app.services.subscription_service import invalidate_vpn_access_cache
        invalidate_manifest_cache()
        invalidate_vpn_access_cache()
        try:
            await sync_unpaid_deny_net(db)
            await sync_all_cell_manifests(db)
        except Exception:
            logging.getLogger(__name__).exception('Inactive account revocation sync deferred')
    return result


async def update_vps_cleanup_meta(db, *, summary='', clear_run_now=True, run_id=None,
                                  status='succeeded', result=None, error=None):
    from fastapi import HTTPException
    row,job=await _locked_job(db)
    if job.get('id') and (run_id!=job['id'] or job.get('status') not in ('running',status)):
        raise HTTPException(409,'Результат относится к другому запуску')
    if status not in ('succeeded','partial','failed'):
        raise HTTPException(422,'Некорректный результат очистки')
    if job.get('id') and job.get('status')==status:
        await db.commit()
        return await get_vps_cleanup_status(db)
    combined=dict(result or {})
    if job.get('users_done'):
        combined['users']=job['users_result']
    job.update(status=status,finished_at=_iso(),result=combined,error=(error or '')[:600] or None)
    _store(row,job)
    await _set_setting(db,LAST_RUN_AT_KEY,job['finished_at'])
    await _set_setting(db,LAST_SUMMARY_KEY,(summary or '')[:2000])
    if clear_run_now:await _set_setting(db,RUN_NOW_KEY,'false')
    await db.commit()
    return await get_vps_cleanup_status(db)


async def wake_vps_cleanup_host():
    from app.services.vpn_kick import _nsenter_host
    try:
        result=await asyncio.to_thread(_nsenter_host,'systemctl start --no-block silent-vps-cleanup.service',timeout=10)
        if result.returncode:raise RuntimeError('host service start failed')
    except Exception:
        logging.getLogger(__name__).warning('Cleanup immediate wakeup failed; queued job kept for timer')
