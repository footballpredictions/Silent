"""Bounded last-good online measurements, shared by API workers.

Only presentation data lives here. No VPN, peer or subscription writes.
Redis WATCH prevents an older concurrent collection from replacing a newer one.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import time

from redis.exceptions import WatchError

logger = logging.getLogger(__name__)
KEY = 'hive:online_snapshot:v1'
LEGACY_KEY = 'hive:vpn_online_shown'
MAX_AGE_SEC = 90.0
FRESH_SEC = 20.0
_cached: dict | None = None


def view(snapshot: dict, *, now: float | None = None) -> dict:
    result = deepcopy(snapshot)
    now = time.time() if now is None else now
    stale, unknown = [], []
    total = 0
    for node in result['nodes']:
        age = max(0.0, now - float(node.get('observed_at') or 0))
        if node.get('count') is None or age > MAX_AGE_SEC:
            node['state'] = 'unknown'
            unknown.append(node['name'])
        elif node.get('missed') or age > FRESH_SEC:
            node['state'] = 'stale'
            stale.append(node['name'])
        else:
            node['state'] = 'fresh'
        total += int(node.get('count') or 0)
    result.update(total=None if unknown else total,
                  state='unknown' if unknown else 'stale' if stale else 'fresh',
                  stale_nodes=stale, unknown_nodes=unknown)
    return result


def build(rows: list[dict], previous: dict | None, started_at: float,
          *, now: float | None = None) -> dict:
    if previous and float(previous['started_at']) > started_at:
        return view(previous, now=now)
    old = {n['id']: n for n in (previous or {}).get('nodes', [])}
    nodes = []
    for row in rows:
        ident = str(row['id'])
        load = row.get('load') or {}
        # A missing status response is not a measured zero / disconnect.
        measured = 'wg_peers_live_3m' in load and load.get('wg_stats_ok', True) is not False
        inactive = row.get('status') not in ('active', 'draining') and not row.get('is_queen')
        if measured or inactive:
            node = dict(id=ident, name=row['name'], count=max(0, int(row['online_count'])),
                        observed_at=started_at, missed=False)
        else:
            prior = old.get(ident) or {}
            node = dict(id=ident, name=row['name'], count=prior.get('count'),
                        observed_at=prior.get('observed_at'), missed=True)
        nodes.append(node)
    return view(dict(started_at=started_at, nodes=nodes), now=now)


def cached() -> dict | None:
    return view(_cached) if _cached is not None else None


def metadata(snapshot: dict | None = None) -> dict:
    snapshot = cached() if snapshot is None else view(snapshot)
    if snapshot is None:
        return {}
    observed = [n['observed_at'] for n in snapshot['nodes'] if n.get('observed_at')]
    return dict(online_status=snapshot['state'],
                online_snapshot_at=snapshot['started_at'],
                online_observed_at=min(observed) if observed else None,
                online_stale_nodes=snapshot['stale_nodes'],
                online_unknown_nodes=snapshot['unknown_nodes'])


async def read(redis) -> dict | None:
    global _cached
    raw = await asyncio.wait_for(redis.get(KEY), timeout=0.35)
    if raw:
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get('nodes'), list):
            raise ValueError('Invalid online snapshot')
        if _cached is None or float(data['started_at']) >= float(_cached['started_at']):
            _cached = data
        return view(_cached)
    return None


async def publish(redis, rows: list[dict], started_at: float) -> dict:
    global _cached

    async def transaction():
        for _ in range(3):
            try:
                async with redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(KEY)
                    raw = await pipe.get(KEY)
                    previous = json.loads(raw) if raw else None
                    snapshot = build(rows, previous, started_at)
                    if previous and float(previous['started_at']) > started_at:
                        return snapshot
                    pipe.multi()
                    pipe.set(KEY, json.dumps(snapshot), ex=int(MAX_AGE_SEC * 2))
                    if snapshot['total'] is None:
                        pipe.delete(LEGACY_KEY)
                    else:
                        pipe.set(LEGACY_KEY, str(snapshot['total']), ex=int(MAX_AGE_SEC))
                    await pipe.execute()
                    return snapshot
            except WatchError:
                continue
        raise RuntimeError('Concurrent online snapshot publication')

    try:
        _cached = await asyncio.wait_for(transaction(), timeout=1.0)
    except Exception as exc:
        logger.warning('Online snapshot shared publication unavailable: %s', type(exc).__name__)
        _cached = build(rows, _cached, started_at)
    return view(_cached)


def apply(rows: list[dict], snapshot: dict) -> None:
    by_id = {n['id']: n for n in snapshot['nodes']}
    for row in rows:
        node = by_id.get(str(row['id']))
        if node is None:
            continue
        row['online_status'] = node['state']
        row['online_observed_at'] = node['observed_at']
        # Legacy per-cell numbers remain integers. New UI hides unknown values.
        if node['state'] != 'unknown':
            row['online_count'] = int(node['count'])
            row['total_online_count'] = int(node['count'])
