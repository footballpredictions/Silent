"""Пересчитать выводы сохранённого отчёта без новых проб и изменения архива."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from typing import Any

from ai.availability_classifier import classify_targets, report_status, report_summary
from ai.availability_model import (
    CHANNEL_AGENT_TCP, ClientSignals, NodeResult, ProbeResult, SEVERITY_ORDER,
    TargetSnapshot, VantageAggregate, scrub_probe_noise_from_report,
)


def _values(cls, data: dict) -> dict:
    return {f.name: data[f.name] for f in fields(cls) if f.name in data}


def _probes(data: dict) -> dict[str, ProbeResult]:
    result = {}
    for channel, raw in data.items():
        if not isinstance(raw, dict) or not isinstance(raw.get('ok'), bool):
            raise ValueError('incomplete local probe')
        result[channel] = ProbeResult(**{**_values(ProbeResult, raw), 'channel': channel})
    return result


def _vantages(data: dict) -> dict[str, VantageAggregate]:
    result = {}
    for channel, raw in data.items():
        if not isinstance(raw, dict) or not isinstance(raw.get('nodes'), list):
            raise ValueError('missing source measurements')
        nodes = []
        for node in raw['nodes']:
            if (not isinstance(node, dict) or not node.get('node')
                    or not isinstance(node.get('ok'), bool)):
                raise ValueError('incomplete vantage node')
            nodes.append(NodeResult(**_values(NodeResult, node)))
        result[channel] = VantageAggregate(channel=channel, nodes=nodes,
                                          source=raw.get('source') or 'ru-external')
    return result


def _snapshot(raw: dict) -> TargetSnapshot:
    if not isinstance(raw, dict) or not all(raw.get(k) for k in ('name', 'host', 'role')):
        raise ValueError('incomplete target')
    snap = TargetSnapshot(**_values(TargetSnapshot, raw))
    snap.local = _probes(raw['local'])
    snap.peer = _probes(raw.get('peer') or {})
    snap.ru = _vantages(raw['ru'])
    snap.world = _vantages(raw.get('world') or {})
    client = raw.get('clients')
    if client is not None and not isinstance(client, dict):
        raise ValueError('incomplete client signals')
    snap.clients = ClientSignals(**_values(ClientSignals, client)) if client else None
    # Старый TargetSnapshot.to_dict не сохранял agent_port, но измерение есть.
    if 'agent_port' not in raw and CHANNEL_AGENT_TCP in snap.ru:
        snap.agent_port = 9100
    return snap


def reclassify_report(report: dict[str, Any]) -> dict[str, Any]:
    """Те же измерения и timestamp, актуальные правила. Неполный архив не озеленяем."""
    result = deepcopy(report)
    scrub_probe_noise_from_report(result)
    targets = result.get('targets')
    if not isinstance(targets, list) or not targets:
        return result
    try:
        snapshots = [_snapshot(raw) for raw in targets]
        verdicts = classify_targets(snapshots)
        status = report_status(verdicts)
        # IP-план зависит от выводов; старый совет по ложной блокировке устарел.
        ip_plan = result.get('ip_plan')
        if isinstance(ip_plan, dict) and ip_plan and not ip_plan.get('executed'):
            from ai.ip_rotate_policy import build_ip_plan

            result['ip_plan'] = build_ip_plan(snapshots, verdicts, dry_run=True, paid_enabled=False)
    except (KeyError, TypeError, ValueError, AttributeError):
        return result
    result.update(
        verdicts=[v.to_dict() for v in verdicts], status=status,
        summary=report_summary(verdicts, status),
        worst_severity=min((v.severity for v in verdicts),
                           key=lambda s: SEVERITY_ORDER.get(s, 9), default='info'),
        classification_version=2,
    )
    return result
