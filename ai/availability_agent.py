"""Агент доступности: видят ли клиенты из РФ наши серверы и если нет — почему.

Что делает за один цикл:
  1. Собирает цели: Улей, соты, proxy-ноды.
  2. Локальные пробы (сервис вообще жив) — TCP/TLS/HTTP/UDP/DNS.
  3. Внешние пробы с российских нод + контрольные вне РФ (отделяют блокировку
     от собственной поломки).
  4. Пробы «сота → Улей» через cell-agent, если он новой версии.
  5. Агрегат клиентских репортов о неудачных подключениях.
  6. Классификация: тип блокировки, уверенность, доказательства и план фикса.
  7. Отчёт в БД + инциденты в журнал Улья.

Безопасность: агент только читает. Он не рестартит `wdtt`, не трогает DNAT,
не снимает WG peer'ы и не меняет конфигурацию — все решения он лишь предлагает.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from ai.availability_classifier import (
    classify_targets,
    plan_incidents,
    report_status,
    report_summary,
)
from ai.availability_model import (
    CHANNEL_AGENT_TCP,
    CHANNEL_API_HTTP,
    CHANNEL_API_TCP,
    CHANNEL_API_TLS,
    CHANNEL_DNS,
    CHANNEL_PING,
    CHANNEL_TLS_NO_SNI,
    CHANNEL_WDTT_UDP,
    CHANNEL_WG_UDP,
    AvailabilityReport,
    ClientSignals,
    NodeResult,
    TARGET_CELL,
    TARGET_QUEEN,
    TargetSnapshot,
    VantageAggregate,
)
from ai.availability_probes import (
    cell_net_probe,
    dns_probe,
    fetch_checkhost_nodes,
    http_probe,
    pick_nodes,
    tcp_probe,
    tls_probe,
    udp_listen_probe,
    vantage_check,
)
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import HiveCell
from app.services import availability_store as store
from app.services.hive_incidents import push_incident

logger = logging.getLogger(__name__)

STARTUP_DELAY_SECONDS = 60
FAILURE_BACKOFF_SECONDS = 180
MIN_SLEEP_SECONDS = 300
FAILURE_STATE_KEY = "agent_failure"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------- цели


async def _collect_targets(db) -> list[TargetSnapshot]:
    from app.services.hive_service import count_online_on_cell
    from app.services.hive_slots import slot_for_cell

    targets: list[TargetSnapshot] = []
    rows = (await db.execute(select(HiveCell))).scalars().all()
    domain = (settings.ADMIN_PUBLIC_HOST or "").strip()

    for cell in rows:
        if not (cell.public_ip or "").strip():
            continue
        if not cell.is_queen and cell.status not in ("active", "draining"):
            continue
        agent_port = settings.HIVE_CELL_AGENT_PORT
        snap = TargetSnapshot(
            name=cell.name,
            host=cell.public_ip.strip(),
            role=TARGET_QUEEN if cell.is_queen else TARGET_CELL,
            api_port=443 if cell.is_queen else 0,
            wdtt_port=int(cell.wdtt_port or 0),
            wg_port=int(cell.wg_port or 0),
            agent_port=0 if cell.is_queen else agent_port,
            domain=domain if cell.is_queen else "",
            status=cell.status,
            note=slot_for_cell(cell),
        )
        try:
            snap.online_count = int(await count_online_on_cell(db, cell.id))
        except Exception:
            snap.online_count = 0
        targets.append(snap)

    # Proxy-ноды сюда не берём: у них свой агент (`proxy_health_loop`), а их SOCKS-порт
    # закрыт для Улья — «недоступен локально» тут означало бы ложную поломку сервиса.
    return targets


def _main_tcp_port(snap: TargetSnapshot) -> tuple[int, str]:
    """Порт, по которому судим о доступности IP как таком."""
    if snap.role == TARGET_QUEEN:
        return snap.api_port or 443, CHANNEL_API_TCP
    return snap.agent_port or settings.HIVE_CELL_AGENT_PORT, CHANNEL_AGENT_TCP


# ------------------------------------------------------------ локальные пробы


async def _run_local_probes(snap: TargetSnapshot) -> None:
    timeout = float(settings.AVAILABILITY_LOCAL_TIMEOUT_SEC)
    jobs: list[asyncio.Future] = []
    port, channel = _main_tcp_port(snap)
    jobs.append(asyncio.ensure_future(tcp_probe(snap.host, port, channel, timeout)))

    if snap.role == TARGET_QUEEN:
        jobs.append(
            asyncio.ensure_future(
                tls_probe(
                    snap.host,
                    snap.api_port or 443,
                    CHANNEL_API_TLS,
                    server_name=snap.domain or None,
                    timeout=timeout + 2,
                )
            )
        )
        jobs.append(
            asyncio.ensure_future(
                tls_probe(
                    snap.host, snap.api_port or 443, CHANNEL_TLS_NO_SNI, server_name=None,
                    timeout=timeout + 2,
                )
            )
        )
        base = f"https://{snap.domain}" if snap.domain else f"https://{snap.host}"
        jobs.append(
            asyncio.ensure_future(
                http_probe(f"{base}/api/health", CHANNEL_API_HTTP, timeout=timeout + 2)
            )
        )
        if snap.domain:
            jobs.append(asyncio.ensure_future(dns_probe(snap.domain, CHANNEL_DNS, timeout)))

    if snap.wdtt_port:
        jobs.append(
            asyncio.ensure_future(udp_listen_probe(snap.host, snap.wdtt_port, CHANNEL_WDTT_UDP))
        )
    if snap.wg_port and snap.wg_port != snap.wdtt_port:
        jobs.append(
            asyncio.ensure_future(udp_listen_probe(snap.host, snap.wg_port, CHANNEL_WG_UDP))
        )

    for result in await asyncio.gather(*jobs, return_exceptions=True):
        if isinstance(result, BaseException):
            logger.warning("availability: локальная проба упала: %s", result)
            continue
        snap.local[result.channel] = result


# ------------------------------------------------- внешние точки наблюдения


def _split_vantage(
    channel: str, results: dict[str, NodeResult]
) -> tuple[VantageAggregate, VantageAggregate]:
    ru = VantageAggregate(channel=channel, source="ru-external")
    world = VantageAggregate(channel=channel, source="world-external")
    for node in results.values():
        (ru if node.country == "ru" else world).nodes.append(node)
    return ru, world


async def _run_external_probes(
    targets: list[TargetSnapshot], *, ru_limit: int, world_limit: int, warnings: list[str]
) -> dict[str, object]:
    node_info = await fetch_checkhost_nodes()
    if not node_info:
        warnings.append(
            "Внешний сервис проверок недоступен: доступность из РФ подтверждается только "
            "клиентской телеметрией."
        )
        return {"ru_nodes": [], "world_nodes": [], "checks": 0}

    ru_nodes, world_nodes = pick_nodes(node_info, ru_limit=ru_limit, world_limit=world_limit)
    if not ru_nodes:
        warnings.append("Среди внешних нод нет российских — вывод о блокировке сделать нельзя.")
    nodes = ru_nodes + world_nodes

    budget = int(settings.AVAILABILITY_MAX_EXTERNAL_CHECKS)
    used = 0
    # Улей первым: если бюджета хватит не на всех, проверяем самое важное.
    max_targets = max(1, int(settings.AVAILABILITY_MAX_EXTERNAL_TARGETS))
    ordered = sorted(targets, key=lambda t: 0 if t.role == TARGET_QUEEN else 1)
    probed = ordered[:max_targets]
    if len(ordered) > len(probed):
        skipped = ", ".join(t.name for t in ordered[max_targets:])
        warnings.append(
            f"Снаружи проверены не все узлы (экономим запросы): пропущены {skipped}. "
            f"Их доступность видна по локальным пробам и пробам со сот."
        )

    async def run(kind: str, host: str, channel: str, snap: TargetSnapshot) -> None:
        nonlocal used
        if used >= budget:
            return
        used += 1
        results = await vantage_check(kind, host, nodes, node_info)
        if not results:
            return
        ru, world = _split_vantage(channel, results)
        if ru.available:
            snap.ru[channel] = ru
        if world.available:
            snap.world[channel] = world

    for snap in probed:
        port, channel = _main_tcp_port(snap)
        await run("ping", snap.host, CHANNEL_PING, snap)
        await run("tcp", f"{snap.host}:{port}", channel, snap)
        if snap.role == TARGET_QUEEN and snap.domain:
            # HTTPS по домену = TLS с нашим SNI: сравнение с TCP по IP отделяет
            # блокировку имени от блокировки адреса.
            await run("http", f"https://{snap.domain}/api/health", CHANNEL_API_TLS, snap)
            await run("dns", snap.domain, CHANNEL_DNS, snap)

    if used >= budget:
        warnings.append(
            f"Достигнут лимит внешних проверок за цикл ({budget}): часть каналов не проверена."
        )
    return {"ru_nodes": ru_nodes, "world_nodes": world_nodes, "checks": used}


# ----------------------------------------------------------- пробы со сот


async def _collect_cell_agents(db) -> list[tuple[str, str, str]]:
    """(имя соты, api_url, секрет) — собираем заранее, чтобы не держать сессию БД."""
    from app.core.security import decrypt_value
    from app.services.hive_service import _validate_outbound_url

    cells = (
        (
            await db.execute(
                select(HiveCell).where(
                    HiveCell.is_queen == False,  # noqa: E712
                    HiveCell.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    out: list[tuple[str, str, str]] = []
    for cell in cells:
        if not cell.api_url or not cell.api_secret_enc:
            continue
        try:
            out.append((cell.name, _validate_outbound_url(cell.api_url), decrypt_value(cell.api_secret_enc)))
        except Exception:
            continue
    return out


async def _run_peer_probes(
    agents: list[tuple[str, str, str]], targets: list[TargetSnapshot], warnings: list[str]
) -> None:
    """Посмотреть на Улей глазами соты: вторая точка наблюдения без внешних сервисов."""
    from ai.availability_model import ProbeResult

    queen = next((t for t in targets if t.role == TARGET_QUEEN), None)
    if queen is None or not agents:
        return

    payload: list[dict] = [
        {"name": "queen_api", "host": queen.host, "port": queen.api_port or 443, "proto": "tcp"},
    ]
    if queen.wdtt_port:
        payload.append(
            {"name": "queen_wdtt", "host": queen.host, "port": queen.wdtt_port, "proto": "udp"}
        )

    for name, api_url, secret in agents:
        try:
            data = await cell_net_probe(api_url, secret, payload)
        except Exception as e:
            warnings.append(f"{name}: пробы со стороны соты недоступны ({e}).")
            continue
        snap = next((t for t in targets if t.name == name), None)
        if snap is None:
            continue
        for item in data.get("results") or []:
            channel = str(item.get("name") or "")
            if not channel:
                continue
            snap.peer[channel] = ProbeResult(
                channel=channel,
                ok=bool(item.get("ok")),
                latency_ms=item.get("latency_ms"),
                error_kind=str(item.get("error_kind") or ""),
                detail=str(item.get("detail") or ""),
                inconclusive=bool(item.get("inconclusive")),
            )


# ------------------------------------------------------- клиентская телеметрия


def _attach_client_signals(targets: list[TargetSnapshot], buckets: dict[str, dict]) -> None:
    for snap in targets:
        raw = buckets.get(snap.note) if snap.note else None
        if raw is None and snap.role == TARGET_QUEEN:
            raw = buckets.get("*")
        if not raw:
            continue
        snap.clients = ClientSignals(
            window_minutes=int(raw.get("window_minutes") or 0),
            reports=int(raw.get("reports") or 0),
            failures=int(raw.get("failures") or 0),
            by_stage=dict(raw.get("by_stage") or {}),
            by_network=dict(raw.get("by_network") or {}),
            by_carrier=dict(raw.get("by_carrier") or {}),
            by_transport=dict(raw.get("by_transport") or {}),
            short_lived_tunnels=int(raw.get("short_lived_tunnels") or 0),
        )


# ----------------------------------------------------------------- прогон


async def run_availability_check(
    *, external: bool | None = None, incidents: bool = True
) -> AvailabilityReport:
    started = time.monotonic()
    warnings: list[str] = []

    # Сессию БД держим только на чтение конфигурации и целей: сетевые пробы идут
    # без открытого соединения, иначе одно медленное внешнее API держит пул.
    async with AsyncSessionLocal() as db:
        cfg = await store.load_settings(db)
        targets = await _collect_targets(db)
        agents = (
            await _collect_cell_agents(db) if settings.AVAILABILITY_PEER_PROBE_ENABLED else []
        )

    if not targets:
        report = AvailabilityReport(
            ts=_utc_now_iso(),
            status="unknown",
            summary="Нет целей для проверки: не настроен Улей и нет активных сот.",
            warnings=["hive_cells пуст или у узлов не задан public_ip."],
        )
        await store.save_report(report.to_dict())
        return report

    await asyncio.gather(*(_run_local_probes(t) for t in targets))

    use_external = cfg["external_enabled"] if external is None else bool(external)
    vantage: dict[str, object] = {"ru_nodes": [], "world_nodes": [], "checks": 0}
    if use_external:
        vantage = await _run_external_probes(
            targets,
            ru_limit=int(cfg["ru_nodes"]),
            world_limit=int(cfg["world_nodes"]),
            warnings=warnings,
        )
    else:
        warnings.append("Внешние пробы отключены настройкой — вывод только по локальным данным.")

    if agents:
        try:
            await _run_peer_probes(agents, targets, warnings)
        except Exception as e:
            warnings.append(f"Пробы между нодами не выполнены: {e}")

    try:
        buckets = await store.aggregate_client_reports(
            int(settings.AVAILABILITY_CLIENT_WINDOW_MINUTES)
        )
        _attach_client_signals(targets, buckets)
    except Exception as e:
        warnings.append(f"Клиентская телеметрия недоступна: {e}")

    verdicts = classify_targets(targets)
    status = report_status(verdicts)
    report = AvailabilityReport(
        ts=_utc_now_iso(),
        status=status,
        summary=report_summary(verdicts, status),
        targets=targets,
        verdicts=verdicts,
        vantage=vantage,
        duration_sec=time.monotonic() - started,
        warnings=warnings,
    )

    await store.save_report(report.to_dict())
    await store.mark_run(status)
    if incidents:
        await _push_incidents(report)
    return report


async def _push_incidents(report: AvailabilityReport) -> None:
    """Проблемные выводы — в журнал Улья, но по одному разу, а не каждый цикл."""
    previous = await store.load_incident_state()
    to_push, state = plan_incidents(
        report.verdicts,
        previous,
        now_ts=time.time(),
        confirm_cycles=int(settings.AVAILABILITY_INCIDENT_CONFIRM_CYCLES),
        renotify_sec=float(settings.AVAILABILITY_INCIDENT_RENOTIFY_HOURS) * 3600.0,
        max_per_cycle=int(settings.AVAILABILITY_INCIDENT_MAX_PER_CYCLE),
    )

    for verdict in to_push:
        fix = verdict.fixes[0] if verdict.fixes else ""
        push_incident(
            source="hive.availability",
            severity="error",
            cell_name=verdict.target,
            cell_ip=verdict.host,
            message=f"{verdict.title}: {verdict.summary}",
            details=f"Решение: {fix} | Признаки: {'; '.join(verdict.evidence[:2])}"
            " | Подробнее: Улей → Доступность и блокировки",
        )

    # Своя поломка живёт отдельным ключом и не теряется при пересчёте сигнатур.
    if FAILURE_STATE_KEY in previous:
        state[FAILURE_STATE_KEY] = previous[FAILURE_STATE_KEY]
    await store.save_incident_state(state)


async def _push_agent_failure(error: str, failures: int) -> None:
    """О собственной поломке агента сообщаем редко: это диагностика, а не событие Улья."""
    renotify = float(settings.AVAILABILITY_INCIDENT_RENOTIFY_HOURS) * 3600.0
    state = await store.load_incident_state()
    last = (state.get(FAILURE_STATE_KEY) or {}).get("notified_at")
    now = time.time()
    if isinstance(last, (int, float)) and (now - float(last)) < renotify:
        return
    push_incident(
        source="hive.availability",
        severity="error",
        message=f"Агент доступности не смог выполнить проверку {failures} раза подряд: {error}",
        details="Диагностика самого агента, VPN и клиенты не затронуты. Проверить исходящий "
        "доступ Улья в интернет и доступность внешнего сервиса проверок.",
    )
    state[FAILURE_STATE_KEY] = {"seen": failures, "notified_at": now}
    await store.save_incident_state(state)


async def _host_is_busy() -> str:
    """Ресурсы важнее диагностики: под нагрузкой цикл лучше пропустить."""
    cpu_limit = float(settings.AVAILABILITY_SKIP_IF_CPU_PERCENT)
    mem_limit = float(settings.AVAILABILITY_SKIP_IF_MEM_PERCENT)
    if cpu_limit <= 0 and mem_limit <= 0:
        return ""
    try:
        from app.services.proc_stats import read_host_load

        load = await asyncio.to_thread(read_host_load)
    except Exception:
        return ""
    cpu = float(load.get("cpu_percent") or 0)
    mem = float(load.get("memory_percent") or 0)
    if cpu_limit > 0 and cpu >= cpu_limit:
        return f"CPU хоста {cpu:.0f}% ≥ {cpu_limit:.0f}%"
    if mem_limit > 0 and mem >= mem_limit:
        return f"RAM хоста {mem:.0f}% ≥ {mem_limit:.0f}%"
    return ""


async def availability_loop() -> None:
    logger.info("Availability agent starting (детекция блокировок DPI/ТСПУ)")
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    failures = 0

    while True:
        interval = int(settings.AVAILABILITY_AGENT_INTERVAL_SEC)
        try:
            async with AsyncSessionLocal() as db:
                cfg = await store.load_settings(db)
            interval = int(cfg["interval_sec"])
            if not cfg["enabled"]:
                logger.debug("availability: агент выключен в настройках — цикл пропущен")
            else:
                busy = await _host_is_busy()
                if busy:
                    logger.info("availability: цикл пропущен, сервер занят (%s)", busy)
                else:
                    report = await run_availability_check()
                    failures = 0
                    logger.info(
                        "availability: %s — %s (за %.1f с)",
                        report.status,
                        report.summary,
                        report.duration_sec,
                    )
                    await store.prune_client_reports()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failures += 1
            logger.warning("availability: цикл упал (%s подряд): %s", failures, e)
            if failures >= 3:
                try:
                    await _push_agent_failure(str(e), failures)
                except Exception:
                    logger.debug("availability: инцидент о поломке агента не записан")
                await asyncio.sleep(FAILURE_BACKOFF_SECONDS)
                failures = 0
        await asyncio.sleep(max(MIN_SLEEP_SECONDS, interval))
