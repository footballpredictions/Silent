"""Классификатор: из матрицы проб — тип блокировки и план фикса.

Чистые функции без сети и БД: агент собирает наблюдения, классификатор только
считает выводы. Так логику можно проверять юнит-тестами и не бояться, что она
что-то сломает на проде.
"""
from __future__ import annotations

from ai.availability_knowledge import (
    KIND_ACTIVE_PROBING,
    KIND_ASN_PARTIAL,
    KIND_DNS_POISONING,
    KIND_HTTP_STUB,
    KIND_IP_BLACKHOLE,
    KIND_MOBILE_SHUTDOWN,
    KIND_NO_VANTAGE,
    KIND_OK,
    KIND_PORT_BLOCK,
    KIND_PROTOCOL_FINGERPRINT,
    KIND_ROUTE_LOSS,
    KIND_RST_INJECTION,
    KIND_SERVICE_DOWN,
    KIND_SNI_BLOCK,
    KIND_THROTTLING,
    KIND_UDP_BLOCK,
    method,
    render_commands,
)
from ai.availability_model import (
    CHANNEL_AGENT_TCP,
    CHANNEL_API_HTTP,
    CHANNEL_API_TCP,
    CHANNEL_API_TLS,
    CHANNEL_DNS,
    CHANNEL_PING,
    CHANNEL_SOCKS_TCP,
    CHANNEL_TLS_DECOY_SNI,
    CHANNEL_TLS_NO_SNI,
    CHANNEL_WDTT_UDP,
    CHANNEL_WG_UDP,
    ERR_HTTP,
    ERR_RESET,
    ERR_TIMEOUT,
    ERR_UNREACHABLE,
    SEVERITY_ORDER,
    STAGE_HANDSHAKE,
    STAGE_TCP,
    STAGE_TLS,
    STAGE_TUNNEL_DEAD,
    TCP_CHANNELS,
    UDP_CHANNELS,
    TargetSnapshot,
    VantageAggregate,
    Verdict,
    carrier_by_asn,
)

# Порог «часть операторов отвалилась»: ниже него считаем частичной блокировкой.
PARTIAL_OK_RATIO = 0.75
# Один таймаут check-host при 3 нодах (2/3) — шум сервиса, не ТСПУ. Нужно ≥2 фейла.
PARTIAL_MIN_FAILS = 2
# Минимум клиентских отказов, ниже которого не делаем выводов по телеметрии.
CLIENT_MIN_FAILURES = 5
# Доля мобильных отказов, при которой это уже режим мобильной сети, а не наш IP.
MOBILE_SHARE = 0.7
# Во сколько раз RTT из РФ должен превышать контрольный, чтобы звать это шейпингом.
THROTTLE_RTT_FACTOR = 3.0
THROTTLE_RTT_FLOOR_MS = 250.0

CHANNEL_TITLES = {
    CHANNEL_API_TCP: "API (TCP)",
    CHANNEL_API_TLS: "API (TLS с нашим доменом)",
    CHANNEL_API_HTTP: "API (HTTP-ответ)",
    CHANNEL_WDTT_UDP: "транспорт wdtt (UDP)",
    CHANNEL_WG_UDP: "WireGuard (UDP)",
    CHANNEL_AGENT_TCP: "cell-agent (TCP)",
    CHANNEL_SOCKS_TCP: "SOCKS-прокси (TCP)",
    CHANNEL_PING: "ICMP ping",
    CHANNEL_DNS: "DNS",
    CHANNEL_TLS_NO_SNI: "TLS без SNI",
    CHANNEL_TLS_DECOY_SNI: "TLS с посторонним SNI",
}

BLOCKING_KINDS = frozenset(
    {
        KIND_IP_BLACKHOLE,
        KIND_PORT_BLOCK,
        KIND_UDP_BLOCK,
        KIND_PROTOCOL_FINGERPRINT,
        KIND_SNI_BLOCK,
        KIND_DNS_POISONING,
        KIND_RST_INJECTION,
        KIND_HTTP_STUB,
        KIND_MOBILE_SHUTDOWN,
    }
)


def channel_title(channel: str) -> str:
    return CHANNEL_TITLES.get(channel, channel)


def _verdict(
    snap: TargetSnapshot,
    kind: str,
    *,
    confidence: float,
    summary: str,
    evidence: list[str],
    channel: str = "",
    extra_fixes: list[str] | None = None,
    port: int = 0,
) -> Verdict:
    m = method(kind)
    fixes = list(m.fixes)
    if extra_fixes:
        fixes = extra_fixes + fixes
    return Verdict(
        target=snap.name,
        host=snap.host,
        kind=kind,
        title=m.title,
        severity=m.severity,
        confidence=max(0.0, min(1.0, confidence)),
        summary=summary,
        evidence=evidence,
        fixes=fixes,
        commands=render_commands(kind, host=snap.host, domain=snap.domain, port=port),
        channel=channel,
    )


def _fail_desc(agg: VantageAggregate) -> str:
    kinds = agg.error_kinds()
    if not kinds:
        return "без ошибок"
    parts = [f"{k}×{v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])]
    return ", ".join(parts)


def _channel_port(snap: TargetSnapshot, channel: str) -> int:
    if channel in (CHANNEL_API_TCP, CHANNEL_API_TLS, CHANNEL_API_HTTP):
        return snap.api_port
    if channel == CHANNEL_WDTT_UDP:
        return snap.wdtt_port
    if channel == CHANNEL_WG_UDP:
        return snap.wg_port
    if channel == CHANNEL_AGENT_TCP:
        return snap.agent_port
    return 0


def _world_confirms_failure(snap: TargetSnapshot, channel: str) -> bool:
    """Отказ виден и вне РФ — значит это не блокировка, а наша поломка/маршрут."""
    world = snap.world_view(channel)
    return bool(world and world.all_failed)


def _dns_verdict(snap: TargetSnapshot) -> Verdict | None:
    agg = snap.ru_view(CHANNEL_DNS)
    if agg is None or not snap.domain:
        return None
    expected = {ip for ip in (snap.host,) if ip}
    world = snap.world_view(CHANNEL_DNS)
    if world:
        expected |= world.resolved_ip_set()
    bad_nodes = [
        n
        for n in agg.nodes
        if n.resolved_ips and expected and not (set(n.resolved_ips) & expected)
    ]
    if not bad_nodes:
        return None
    sample = bad_nodes[0]
    evidence = [
        f"{len(bad_nodes)} из {agg.total} российских нод резолвят {snap.domain} мимо наших адресов.",
        f"Пример: {sample.node} → {', '.join(sample.resolved_ips)} (ожидали {', '.join(sorted(expected))}).",
    ]
    return _verdict(
        snap,
        KIND_DNS_POISONING,
        confidence=0.6 + 0.35 * (len(bad_nodes) / max(agg.total, 1)),
        summary=f"DNS-ответы по домену {snap.domain} подменяются у операторов.",
        evidence=evidence,
        channel=CHANNEL_DNS,
    )


def _blackhole_verdict(snap: TargetSnapshot) -> Verdict | None:
    views = {c: snap.ru_view(c) for c in snap.ru_channels()}
    views = {c: v for c, v in views.items() if v is not None and c != CHANNEL_DNS}
    if len(views) < 2:
        return None
    if any(not v.all_failed for v in views.values()):
        return None
    # Локально сервисы живы — иначе это не блокировка.
    local_alive = [c for c in views if snap.local_ok(c) is True]
    if not local_alive:
        return None
    kinds: set[str] = set()
    for v in views.values():
        kinds |= set(v.error_kinds())
    if kinds - {ERR_TIMEOUT, ERR_UNREACHABLE}:
        return None
    if any(_world_confirms_failure(snap, c) for c in views):
        return None

    if kinds == {ERR_UNREACHABLE}:
        return _verdict(
            snap,
            KIND_ROUTE_LOSS,
            confidence=0.7,
            summary=f"{snap.host} недостижим по маршруту со всех российских нод.",
            evidence=[
                f"Каналы {', '.join(channel_title(c) for c in views)} — unreachable со всех нод.",
                "Локально сервисы отвечают, отказ приходит как ICMP unreachable.",
            ],
        )

    confidence = 0.8 if CHANNEL_PING in views else 0.7
    if snap.world:
        confidence += 0.1
    evidence = [
        f"Все проверенные каналы ({', '.join(channel_title(c) for c in views)}) — "
        f"молчание со всех {max(v.total for v in views.values())} российских нод.",
        f"Ошибки: {_fail_desc(next(iter(views.values())))} — ни одного refused, значит пакеты дропаются.",
        "Локально те же порты отвечают, вне РФ адрес доступен.",
    ]
    return _verdict(
        snap,
        KIND_IP_BLACKHOLE,
        confidence=confidence,
        summary=f"IP {snap.host} заблокирован целиком: из РФ не отвечает ни один порт.",
        evidence=evidence,
    )


def _sni_verdict(snap: TargetSnapshot) -> Verdict | None:
    tls = snap.ru_view(CHANNEL_API_TLS)
    if tls is None or not tls.all_failed:
        return None
    tcp = snap.ru_view(CHANNEL_API_TCP)
    no_sni = snap.ru_view(CHANNEL_TLS_NO_SNI) or snap.ru_view(CHANNEL_TLS_DECOY_SNI)
    if tcp is None or not tcp.all_ok:
        return None
    if snap.local_ok(CHANNEL_API_TLS) is not True:
        return None
    # Ответ пришёл, но с чужим кодом — это подмена ответа, а не блок имени.
    if tls.dominant_error() == ERR_HTTP:
        return None
    evidence = [
        f"TCP {snap.api_port} из РФ открывается на всех {tcp.total} нодах.",
        f"TLS с доменом {snap.domain or snap.host} не проходит: {_fail_desc(tls)}.",
    ]
    confidence = 0.65
    if no_sni is not None and no_sni.all_ok:
        evidence.append("То же соединение без нашего SNI проходит — режется именно имя.")
        confidence = 0.85
    return _verdict(
        snap,
        KIND_SNI_BLOCK,
        confidence=confidence,
        summary=f"Блокировка по имени {snap.domain or snap.host}, сам IP доступен.",
        evidence=evidence,
        channel=CHANNEL_API_TLS,
        port=snap.api_port,
    )


def _http_stub_verdict(snap: TargetSnapshot) -> Verdict | None:
    http = snap.ru_view(CHANNEL_API_HTTP) or snap.ru_view(CHANNEL_API_TLS)
    if http is None or http.all_ok:
        return None
    if http.dominant_error() != ERR_HTTP:
        return None
    if snap.local_ok(CHANNEL_API_HTTP) is not True:
        return None
    sample = next((n for n in http.failing_nodes() if n.detail), None)
    evidence = [
        f"{http.fail_count} из {http.total} российских нод получают не наш ответ.",
    ]
    if sample:
        evidence.append(f"Пример: {sample.node} → {sample.detail}.")
    return _verdict(
        snap,
        KIND_HTTP_STUB,
        confidence=0.7,
        summary="Ответ подменяется в сети оператора (заглушка/редирект).",
        evidence=evidence,
        channel=CHANNEL_API_HTTP,
        port=snap.api_port,
    )


def _channel_verdicts(snap: TargetSnapshot) -> list[Verdict]:
    """Пер-канальные выводы: сервис лежит, порт режется, UDP срезан, RST-инъекция."""
    out: list[Verdict] = []
    udp_views = {c: snap.ru_view(c) for c in UDP_CHANNELS if snap.ru_view(c)}
    tcp_views = {c: snap.ru_view(c) for c in TCP_CHANNELS if snap.ru_view(c)}
    udp_all_dead = bool(udp_views) and all(v.all_failed for v in udp_views.values())
    tcp_all_ok = bool(tcp_views) and all(v.all_ok for v in tcp_views.values())

    if udp_all_dead and tcp_all_ok:
        ports = [p for p in (snap.wdtt_port, snap.wg_port) if p]
        out.append(
            _verdict(
                snap,
                KIND_UDP_BLOCK,
                confidence=0.8,
                summary="UDP срезан: TCP к тому же адресу проходит, UDP-транспорт — нет.",
                evidence=[
                    f"UDP-каналы ({', '.join(channel_title(c) for c in udp_views)}) мертвы "
                    f"на всех {max(v.total for v in udp_views.values())} нодах.",
                    f"TCP-каналы ({', '.join(channel_title(c) for c in tcp_views)}) проходят полностью.",
                    f"Порты UDP: {', '.join(str(p) for p in ports) or 'нет данных'}.",
                ],
                channel=CHANNEL_WDTT_UDP if snap.wdtt_port else CHANNEL_WG_UDP,
                port=snap.wdtt_port or snap.wg_port,
            )
        )

    for channel in snap.ru_channels():
        if channel in (CHANNEL_DNS, CHANNEL_PING, CHANNEL_API_TLS, CHANNEL_API_HTTP):
            continue
        agg = snap.ru_view(channel)
        if agg is None or agg.all_ok:
            continue
        port = _channel_port(snap, channel)
        local = snap.local_ok(channel)

        if local is False:
            out.append(
                _verdict(
                    snap,
                    KIND_SERVICE_DOWN,
                    confidence=0.9,
                    summary=f"{channel_title(channel)} не отвечает и локально — это не блокировка.",
                    evidence=[
                        f"Локальная проба {channel_title(channel)} на порт {port or '?'} не прошла.",
                        f"Из РФ: {_fail_desc(agg)}.",
                    ],
                    channel=channel,
                    port=port,
                )
            )
            continue

        dominant = agg.dominant_error()
        if dominant == ERR_RESET and not _world_confirms_failure(snap, channel):
            out.append(
                _verdict(
                    snap,
                    KIND_RST_INJECTION,
                    confidence=0.75,
                    summary=f"{channel_title(channel)} рвётся сбросом соединения из РФ.",
                    evidence=[
                        f"{agg.fail_count} из {agg.total} нод получают reset, а не таймаут.",
                        "Локально соединение живёт — сброс приходит от промежуточного узла.",
                    ],
                    channel=channel,
                    port=port,
                )
            )
            continue

        if dominant == ERR_UNREACHABLE:
            out.append(
                _verdict(
                    snap,
                    KIND_ROUTE_LOSS,
                    confidence=0.6,
                    summary=f"{channel_title(channel)} недостижим по маршруту.",
                    evidence=[f"Из РФ: {_fail_desc(agg)}.", "Локально порт слушает."],
                    channel=channel,
                    port=port,
                )
            )
            continue

        if agg.all_failed:
            if udp_all_dead and channel in UDP_CHANNELS:
                continue  # уже покрыто выводом про UDP
            alive = [
                c
                for c in snap.ru_channels()
                if c != channel
                and c != CHANNEL_DNS
                and (snap.ru_view(c) is not None and snap.ru_view(c).all_ok)  # type: ignore[union-attr]
            ]
            if not alive:
                continue  # это blackhole, его считает отдельное правило
            out.append(
                _verdict(
                    snap,
                    KIND_PORT_BLOCK,
                    confidence=0.8,
                    summary=f"Порт {port or '?'} ({channel_title(channel)}) режется, сам IP доступен.",
                    evidence=[
                        f"{channel_title(channel)} мертв на всех {agg.total} нодах: {_fail_desc(agg)}.",
                        f"Живые каналы того же IP: {', '.join(channel_title(c) for c in alive)}.",
                        f"Локально порт {port or '?'} отвечает.",
                    ],
                    channel=channel,
                    extra_fixes=[
                        f"Добавить альтернативный вход на порт 443/8443 через DNAT на {port or 'текущий порт'} "
                        f"({snap.name}) — без рестарта сервиса.",
                    ],
                    port=port,
                )
            )
            continue

        if agg.ok_ratio < PARTIAL_OK_RATIO and agg.fail_count >= PARTIAL_MIN_FAILS:
            failing = agg.failing_nodes()
            carriers = sorted({carrier_by_asn(n.asn) or n.asn for n in failing if n.asn})
            out.append(
                _verdict(
                    snap,
                    KIND_ASN_PARTIAL,
                    confidence=0.6,
                    summary=(
                        f"{channel_title(channel)} доступен не у всех операторов "
                        f"({agg.ok_count} из {agg.total})."
                    ),
                    evidence=[
                        f"Не отвечают: {', '.join(carriers) or 'ноды без ASN'}.",
                        f"Ошибки: {_fail_desc(agg)}.",
                    ],
                    channel=channel,
                    port=port,
                )
            )

    return out


def _client_verdicts(snap: TargetSnapshot) -> list[Verdict]:
    signals = snap.clients
    if signals is None or signals.failures < CLIENT_MIN_FAILURES:
        return []
    out: list[Verdict] = []

    mobile = int(signals.by_network.get("mobile", 0))
    if signals.failures and mobile / signals.failures >= MOBILE_SHARE:
        transport = [c for c in snap.ru_channels() if c != CHANNEL_DNS]
        if transport and all(snap.ru[c].all_ok for c in transport):
            carriers = sorted(signals.by_carrier.items(), key=lambda kv: -kv[1])[:3]
            out.append(
                _verdict(
                    snap,
                    KIND_MOBILE_SHUTDOWN,
                    confidence=0.7,
                    summary="Отказы почти только на мобильных сетях — ограничения у операторов.",
                    evidence=[
                        f"{mobile} из {signals.failures} отказов за {signals.window_minutes} мин "
                        f"пришли с network_type=mobile.",
                        f"Операторы: {', '.join(f'{k}×{v}' for k, v in carriers) or 'не переданы'}.",
                        "Внешние пробы из РФ при этом проходят — наш IP доступен.",
                    ],
                )
            )

    # Внешние сервисы не умеют честно проверять наш UDP (wdtt/WG не отвечают на мусор),
    # поэтому UDP-доступность из РФ различаем по стадии отказа у клиентов.
    handshake = signals.stage(STAGE_HANDSHAKE)
    dead = signals.stage(STAGE_TUNNEL_DEAD)
    early = signals.stage(STAGE_TCP) + signals.stage(STAGE_TLS)
    api_ok = any(snap.ru[c].all_ok for c in snap.ru_channels() if c in TCP_CHANNELS)

    if api_ok and (dead + signals.short_lived_tunnels) >= CLIENT_MIN_FAILURES:
        out.append(
            _verdict(
                snap,
                KIND_PROTOCOL_FINGERPRINT,
                confidence=0.7 if signals.short_lived_tunnels else 0.6,
                summary="Туннель поднимается и умирает — похоже на DPI по отпечатку потока.",
                evidence=[
                    f"{dead} отказов tunnel_dead и {signals.short_lived_tunnels} короткоживущих "
                    f"туннелей за {signals.window_minutes} мин.",
                    f"На стадиях tcp/tls отказов только {early} — транспорт до сервера доходит.",
                    "TCP-порты из РФ отвечают: адрес и порт не заблокированы.",
                ],
            )
        )
    elif api_ok and handshake >= CLIENT_MIN_FAILURES and handshake > early:
        udp = signals.transport("udp")
        udp_share = (udp / handshake) if handshake else 0.0
        kind = KIND_UDP_BLOCK if udp_share >= 0.7 else KIND_PROTOCOL_FINGERPRINT
        out.append(
            _verdict(
                snap,
                kind,
                confidence=0.6,
                summary=(
                    "Рукопожатие по UDP не завершается, при этом TCP к тому же адресу живой."
                    if kind == KIND_UDP_BLOCK
                    else "Рукопожатие не завершается при доступном порте — признак DPI."
                ),
                evidence=[
                    f"{handshake} отказов на стадии handshake против {early} на tcp/tls.",
                    f"Из них по UDP-транспорту: {udp}.",
                    "TCP-порты из РФ отвечают — значит это не блок IP и не падение сервиса.",
                ],
                channel=CHANNEL_WDTT_UDP if kind == KIND_UDP_BLOCK else "",
                port=snap.wdtt_port if kind == KIND_UDP_BLOCK else 0,
            )
        )

    return out


def _throttling_verdict(snap: TargetSnapshot) -> Verdict | None:
    ru = snap.ru_view(CHANNEL_PING) or snap.ru_view(CHANNEL_API_TCP)
    if ru is None or not ru.all_ok:
        return None
    ru_rtt = ru.median_latency_ms()
    if ru_rtt is None or ru_rtt < THROTTLE_RTT_FLOOR_MS:
        return None
    world = snap.world_view(ru.channel)
    world_rtt = world.median_latency_ms() if world else None
    if world_rtt is None or world_rtt <= 0:
        return None
    if ru_rtt < world_rtt * THROTTLE_RTT_FACTOR:
        return None
    return _verdict(
        snap,
        KIND_THROTTLING,
        confidence=0.55,
        summary=f"Канал проходит, но из РФ медленнее в {ru_rtt / world_rtt:.1f} раза.",
        evidence=[
            f"Медианный RTT из РФ: {ru_rtt:.0f} мс, контрольный вне РФ: {world_rtt:.0f} мс.",
            f"Канал: {channel_title(ru.channel)}, потерь по нодам нет.",
        ],
        channel=ru.channel,
    )


def classify_target(snap: TargetSnapshot) -> list[Verdict]:
    verdicts: list[Verdict] = []

    dns = _dns_verdict(snap)
    if dns:
        verdicts.append(dns)

    blackhole = _blackhole_verdict(snap)
    if blackhole:
        verdicts.append(blackhole)
    else:
        sni = _sni_verdict(snap)
        if sni:
            verdicts.append(sni)
        stub = _http_stub_verdict(snap)
        if stub:
            verdicts.append(stub)
        verdicts.extend(_channel_verdicts(snap))
        throttle = _throttling_verdict(snap)
        if throttle:
            verdicts.append(throttle)

    verdicts.extend(_client_verdicts(snap))

    if not verdicts:
        if not snap.ru_channels():
            if snap.clients is None or not snap.clients.available:
                verdicts.append(
                    _verdict(
                        snap,
                        KIND_NO_VANTAGE,
                        confidence=0.4,
                        summary="Нет данных из РФ: доступность для клиентов не подтверждена.",
                        evidence=["Внешние пробы не выполнились, клиентских репортов нет."],
                    )
                )
            return verdicts
        verdicts.append(
            _verdict(
                snap,
                KIND_OK,
                confidence=0.9,
                summary=f"{snap.name}: все каналы доступны из РФ.",
                evidence=[
                    f"Проверено каналов: {len(snap.ru_channels())}, "
                    f"нод: {max((v.total for v in snap.ru.values()), default=0)}."
                ],
            )
        )
    return verdicts


def _dedupe(verdicts: list[Verdict]) -> list[Verdict]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Verdict] = []
    for v in verdicts:
        key = (v.target, v.kind, v.channel)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def sort_verdicts(verdicts: list[Verdict]) -> list[Verdict]:
    return sorted(
        verdicts,
        key=lambda v: (SEVERITY_ORDER.get(v.severity, 9), -v.confidence, v.target),
    )


def classify_targets(snapshots: list[TargetSnapshot]) -> list[Verdict]:
    out: list[Verdict] = []
    for snap in snapshots:
        out.extend(classify_target(snap))
    return sort_verdicts(_dedupe(out))


def report_status(verdicts: list[Verdict]) -> str:
    kinds = {v.kind for v in verdicts}
    if KIND_SERVICE_DOWN in kinds:
        return "down"
    if kinds & BLOCKING_KINDS:
        return "blocked"
    if kinds & {KIND_ASN_PARTIAL, KIND_THROTTLING, KIND_ROUTE_LOSS, KIND_ACTIVE_PROBING}:
        return "degraded"
    # «Неизвестно» только если из РФ не подтверждён ни один узел: когда Улей виден,
    # непроверенная снаружи сота не должна гасить общий статус.
    if KIND_NO_VANTAGE in kinds and KIND_OK not in kinds:
        return "unknown"
    return "ok"


def incident_signature(verdict: Verdict) -> str:
    return f"{verdict.target}|{verdict.kind}|{verdict.channel}"


def plan_incidents(
    verdicts: list[Verdict],
    previous: dict[str, dict],
    *,
    now_ts: float,
    confirm_cycles: int,
    renotify_sec: float,
    max_per_cycle: int,
) -> tuple[list[Verdict], dict[str, dict]]:
    """Что писать в журнал инцидентов Улья, а что промолчать.

    Журнал общий для всего Улья, поэтому агент обязан быть тихим:
      * пишем только подтверждённое (проблема видна N циклов подряд) — гасит флап;
      * повтор о той же проблеме — не чаще, чем раз в `renotify_sec`;
      * не больше `max_per_cycle` записей за цикл (verdicts уже отсортированы по важности);
      * проблема исчезла — сигнатура забывается, в следующий раз сообщим заново.

    Чистая функция: время и прошлое состояние приходят аргументами, чтобы это
    поведение можно было проверить тестом, а не на проде.
    """
    to_push: list[Verdict] = []
    state: dict[str, dict] = {}

    for verdict in verdicts:
        if verdict.kind == KIND_OK or verdict.severity not in ("critical", "error"):
            continue
        key = incident_signature(verdict)
        prev = previous.get(key) or {}
        entry = {
            "seen": int(prev.get("seen") or 0) + 1,
            "notified_at": prev.get("notified_at"),
        }
        state[key] = entry

        if entry["seen"] < max(1, confirm_cycles) or len(to_push) >= max(0, max_per_cycle):
            continue
        last = prev.get("notified_at")
        if isinstance(last, (int, float)) and (now_ts - float(last)) < renotify_sec:
            continue
        entry["notified_at"] = now_ts
        to_push.append(verdict)

    return to_push, state


def report_summary(verdicts: list[Verdict], status: str) -> str:
    if status == "ok":
        targets = sorted({v.target for v in verdicts})
        return f"Все проверенные узлы доступны из РФ ({', '.join(targets) or 'нет целей'})."
    top = [v for v in verdicts if v.kind not in (KIND_OK,)]
    if not top:
        return "Изменений нет."
    head = top[0]
    rest = len(top) - 1
    tail = f" и ещё {rest} замечание(й)" if rest > 0 else ""
    return f"{head.target}: {head.title} — {head.summary}{tail}"
