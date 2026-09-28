"""Результаты асинхронных внешних проверок: ждать, сохранять частичные данные."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai import availability_probes as probes


async def test_default_polling_waits_for_delayed_results():
    # API начинает проверку, возвращает null первые 5 опросов, затем измерение.
    polls = 0
    elapsed = 0.0
    async def sleep(delay):
        nonlocal elapsed
        elapsed += delay
    def handle(request):
        nonlocal polls
        if '/check-tcp' in request.url.path:
            return httpx.Response(200, json={'ok':1,'request_id':'fixture','nodes':{'ru1':[]}})
        polls += 1
        return httpx.Response(200, json={'ru1':None if polls <= 5 else [{'time':0.055,'address':'192.0.2.1'}]})
    real_client = httpx.AsyncClient
    with patch.object(probes.httpx, 'AsyncClient', side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle), **kw)), patch.object(probes.asyncio, 'sleep', sleep):
        results = await probes.vantage_check('tcp','192.0.2.1:9100',['ru1'],{'ru1':{'country':'ru'}})
    assert results['ru1'].ok, f"получено {results['ru1'].error_kind} после {polls} опросов/{elapsed} с"


async def test_partial_result_is_not_lost_on_later_poll_error():
    polls = 0
    async def sleep(delay): pass
    def handle(request):
        nonlocal polls
        if '/check-tcp' in request.url.path:
            return httpx.Response(200, json={'ok':1,'request_id':'fixture','nodes':{'ru1':[], 'ru2':[]}})
        polls += 1
        if polls == 1:
            return httpx.Response(200,json={'ru1':[{'time':0.055,'address':'192.0.2.1'}], 'ru2':None})
        if polls == 2:
            raise httpx.ReadTimeout('temporary service timeout',request=request)
        return httpx.Response(200,json={'ru1':None, 'ru2':[{'error':'Connection refused'}]})
    real_client = httpx.AsyncClient
    with patch.object(probes.httpx,'AsyncClient',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw)), patch.object(probes.asyncio,'sleep',sleep):
        results=await probes.vantage_check('tcp','192.0.2.1:9100',['ru1','ru2'],{'ru1':{'country':'ru'},'ru2':{'country':'ru'}})
    assert results.get('ru1') and results['ru1'].ok, 'готовое измерение потеряно при временном сбое polling'
    assert results.get('ru2') and results['ru2'].error_kind == 'refused', 'реальный отказ порта потерян'


async def test_polling_does_not_overwrite_completed_nodes_with_null():
    polls=0
    async def sleep(delay): pass
    def handle(request):
        nonlocal polls
        if '/check-tcp' in request.url.path:
            return httpx.Response(200,json={'ok':1,'request_id':'fixture','nodes':{'ru1':[], 'ru2':[]}})
        polls += 1
        return httpx.Response(200,json={'ru1':[{'time':0.055}] if polls==1 else None, 'ru2':None if polls==1 else [{'time':0.075}]})
    real_client=httpx.AsyncClient
    with patch.object(probes.httpx,'AsyncClient',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw)), patch.object(probes.asyncio,'sleep',sleep):
        results=await probes.vantage_check('tcp','192.0.2.1:9100',['ru1','ru2'],{'ru1':{'country':'ru'},'ru2':{'country':'ru'}})
    assert all(n.ok for n in results.values()), 'готовое измерение затёрто последующим null'


async def test_provider_failure_is_not_target_timeout():
    def handle(request):
        return httpx.Response(429,json={'error':'rate limit'})
    real_client=httpx.AsyncClient
    with patch.object(probes.httpx,'AsyncClient',side_effect=lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw)):
        results=await probes.vantage_check('tcp','192.0.2.1:9100',['ru1'],{'ru1':{'country':'ru'}})
    assert results.get('ru1') and results['ru1'].error_kind=='probe_error', 'отказ сервиса должен сохранять причину без обвинения сервера'


if __name__ == '__main__':
    failed=0
    for name,fn in sorted(list(globals().items())):
        if name.startswith('test_'):
            try:
                asyncio.run(fn())
                print('ok '+name)
            except AssertionError as exc:
                print('FAIL '+name+': '+str(exc))
                failed += 1
    raise SystemExit(bool(failed))
