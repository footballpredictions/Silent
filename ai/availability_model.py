"""Типы данных агента доступности.

Только stdlib: модуль импортируется в юнит-тестах без БД, httpx и FastAPI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Нормализованные причины отказа — на них опирается классификатор.
ERR_NONE = ""
ERR_TIMEOUT = "timeout"          # SYN/пакет ушёл, ответа нет (drop)
ERR_REFUSED = "refused"          # RST на SYN: порт закрыт / сервис не слушает
ERR_RESET = "reset"              # соединение установилось и было сброшено
ERR_UNREACHABLE = "unreachable"  # ICMP unreachable / нет маршрута
ERR_DNS = "dns"                  # имя не резолвится
ERR_TLS = "tls"                  # TCP есть, TLS-рукопожатие не прошло
ERR_HTTP = "http"                # ответ есть, но не тот (заглушка/редирект РКН)
ERR_OTHER = "other"

# Стадии, на которых клиент может упасть (клиентская телеметрия).
STAGE_DNS = "dns"
STAGE_TCP = "tcp"
STAGE_TLS = "tls"
STAGE_HANDSHAKE = "handshake"      # WG/wdtt рукопожатие не завершилось
STAGE_TUNNEL_DEAD = "tunnel_dead"  # туннель поднялся и умер
STAGE_API = "api"

# Роли целей проверки.
TARGET_QUEEN = "queen"
TARGET_CELL = "cell"
TARGET_PROXY = "proxy"
TARGET_DOMAIN = "domain"

# Что именно проверяем на цели.
CHANNEL_API_TCP = "api_tcp"
CHANNEL_API_TLS = "api_tls"
CHANNEL_API_HTTP = "api_http"
CHANNEL_WDTT_UDP = "wdtt_udp"
CHANNEL_WG_UDP = "wg_udp"
CHANNEL_AGENT_TCP = "agent_tcp"
CHANNEL_PING = "ping"
CHANNEL_DNS = "dns"
CHANNEL_TLS_NO_SNI = "tls_no_sni"
CHANNEL_TLS_DECOY_SNI = "tls_decoy_sni"
CHANNEL_SOCKS_TCP = "socks_tcp"

UDP_CHANNELS = frozenset({CHANNEL_WDTT_UDP, CHANNEL_WG_UDP})
TCP_CHANNELS = frozenset({CHANNEL_API_TCP, CHANNEL_AGENT_TCP, CHANNEL_SOCKS_TCP})

SEVERITY_ORDER = {"critical": 0, "error": 1, "warning": 2, "info": 3}

# ASN мобильных операторов РФ — трафик через них режут агрессивнее фиксированного.
RU_MOBILE_ASNS = {
    "AS8359": "МТС",
    "AS31133": "МегаФон",
    "AS3216": "Билайн",
    "AS48642": "Tele2 / T2",
    "AS31213": "Yota / МегаФон",
    "AS12714": "МОТИВ",
    "AS25159": "МегаФон Ритейл",
}


def is_mobile_asn(asn: str) -> bool:
    return (asn or "").strip().upper() in RU_MOBILE_ASNS


def carrier_by_asn(asn: str) -> str:
    return RU_MOBILE_ASNS.get((asn or "").strip().upper(), "")


def client_report_age_sec(age_sec: Any, max_age_sec: int) -> int | None:
    """Сколько репорт пролежал в клиентской очереди, приведённое к секундам.

    Клиент сообщает об отказе, а отказ и означает, что отправить сразу не вышло:
    доставка бывает через часы. Без поправки на возраст отложенная пачка легла бы
    в текущее окно, и агент увидел бы блокировку, которой уже нет.

    `None` — репорт старше срока хранения, писать его незачем. Отрицательный
    возраст (часы клиента убежали вперёд) считаем нулём.
    """
    if age_sec is None:
        return 0
    try:
        age = int(age_sec)
    except (TypeError, ValueError):
        return 0
    if age > max_age_sec:
        return None
    return max(0, age)


@dataclass
class ProbeResult:
    """Одна проба с одной точки наблюдения."""

    channel: str
    ok: bool
    latency_ms: float | None = None
    error_kind: str = ERR_NONE
    detail: str = ""
    resolved_ips: tuple[str, ...] = ()
    inconclusive: bool = False  # UDP без ответа: ни подтвердить, ни опровергнуть

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "ok": self.ok,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms is not None else None,
            "error_kind": self.error_kind,
            "detail": self.detail[:300],
            "resolved_ips": list(self.resolved_ips),
            "inconclusive": self.inconclusive,
        }


@dataclass
class NodeResult:
    """Результат с внешней точки наблюдения (нода в РФ)."""

    node: str
    country: str = "ru"
    city: str = ""
    asn: str = ""
    ok: bool = False
    latency_ms: float | None = None
    error_kind: str = ERR_NONE
    detail: str = ""
    resolved_ips: tuple[str, ...] = ()

    @property
    def mobile(self) -> bool:
        return is_mobile_asn(self.asn)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node": self.node,
            "country": self.country,
            "city": self.city,
            "asn": self.asn,
            "carrier": carrier_by_asn(self.asn),
            "ok": self.ok,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms is not None else None,
            "error_kind": self.error_kind,
            "detail": self.detail[:200],
            "resolved_ips": list(self.resolved_ips),
        }


@dataclass
class VantageAggregate:
    """Сводка по каналу со всех внешних нод."""

    channel: str
    nodes: list[NodeResult] = field(default_factory=list)
    source: str = "ru-external"

    @property
    def total(self) -> int:
        return len(self.nodes)

    @property
    def ok_count(self) -> int:
        return sum(1 for n in self.nodes if n.ok)

    @property
    def fail_count(self) -> int:
        return self.total - self.ok_count

    @property
    def available(self) -> bool:
        """Была ли вообще возможность посмотреть с этой точки."""
        return self.total > 0

    @property
    def all_failed(self) -> bool:
        return self.available and self.ok_count == 0

    @property
    def all_ok(self) -> bool:
        return self.available and self.fail_count == 0

    @property
    def ok_ratio(self) -> float:
        return (self.ok_count / self.total) if self.total else 0.0

    def error_kinds(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in self.nodes:
            if n.ok or not n.error_kind:
                continue
            out[n.error_kind] = out.get(n.error_kind, 0) + 1
        return out

    def dominant_error(self) -> str:
        kinds = self.error_kinds()
        if not kinds:
            return ERR_NONE
        return max(kinds.items(), key=lambda kv: kv[1])[0]

    def median_latency_ms(self) -> float | None:
        vals = sorted(n.latency_ms for n in self.nodes if n.ok and n.latency_ms is not None)
        if not vals:
            return None
        mid = len(vals) // 2
        if len(vals) % 2:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2

    def resolved_ip_set(self) -> set[str]:
        out: set[str] = set()
        for n in self.nodes:
            out.update(n.resolved_ips)
        return out

    def failing_nodes(self) -> list[NodeResult]:
        return [n for n in self.nodes if not n.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "source": self.source,
            "total": self.total,
            "ok": self.ok_count,
            "failed": self.fail_count,
            "ok_ratio": round(self.ok_ratio, 3),
            "median_latency_ms": (
                round(self.median_latency_ms(), 1) if self.median_latency_ms() is not None else None
            ),
            "error_kinds": self.error_kinds(),
            "nodes": [n.to_dict() for n in self.nodes],
        }


@dataclass
class ClientSignals:
    """Агрегат клиентских репортов о неудачных подключениях."""

    window_minutes: int = 0
    reports: int = 0
    failures: int = 0
    by_stage: dict[str, int] = field(default_factory=dict)
    by_network: dict[str, int] = field(default_factory=dict)
    by_carrier: dict[str, int] = field(default_factory=dict)
    by_transport: dict[str, int] = field(default_factory=dict)
    short_lived_tunnels: int = 0

    @property
    def available(self) -> bool:
        return self.reports > 0

    def stage(self, name: str) -> int:
        return int(self.by_stage.get(name, 0))

    def transport(self, name: str) -> int:
        return int(self.by_transport.get(name, 0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_minutes": self.window_minutes,
            "reports": self.reports,
            "failures": self.failures,
            "by_stage": dict(self.by_stage),
            "by_network": dict(self.by_network),
            "by_carrier": dict(self.by_carrier),
            "by_transport": dict(self.by_transport),
            "short_lived_tunnels": self.short_lived_tunnels,
        }


@dataclass
class TargetSnapshot:
    """Все наблюдения по одной цели (Улей / сота / proxy / домен)."""

    name: str
    host: str
    role: str = TARGET_CELL
    api_port: int = 443
    wdtt_port: int = 0
    wg_port: int = 0
    agent_port: int = 0
    domain: str = ""
    local: dict[str, ProbeResult] = field(default_factory=dict)
    ru: dict[str, VantageAggregate] = field(default_factory=dict)
    world: dict[str, VantageAggregate] = field(default_factory=dict)
    peer: dict[str, ProbeResult] = field(default_factory=dict)
    clients: ClientSignals | None = None
    online_count: int = 0
    status: str = ""
    note: str = ""

    def local_ok(self, channel: str) -> bool | None:
        pr = self.local.get(channel)
        if pr is None or pr.inconclusive:
            return None
        return pr.ok

    def ru_view(self, channel: str) -> VantageAggregate | None:
        agg = self.ru.get(channel)
        if agg is None or not agg.available:
            return None
        return agg

    def world_view(self, channel: str) -> VantageAggregate | None:
        """Контрольная точка вне РФ: отделяет блокировку от поломки сервера."""
        agg = self.world.get(channel)
        if agg is None or not agg.available:
            return None
        return agg

    def ru_channels(self) -> list[str]:
        return [c for c, agg in self.ru.items() if agg.available]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "role": self.role,
            "api_port": self.api_port,
            "wdtt_port": self.wdtt_port,
            "wg_port": self.wg_port,
            "domain": self.domain,
            "status": self.status,
            "online_count": self.online_count,
            "note": self.note,
            "local": {k: v.to_dict() for k, v in self.local.items()},
            "ru": {k: v.to_dict() for k, v in self.ru.items()},
            "world": {k: v.to_dict() for k, v in self.world.items()},
            "peer": {k: v.to_dict() for k, v in self.peer.items()},
            "clients": self.clients.to_dict() if self.clients else None,
        }


@dataclass
class Verdict:
    """Вывод по цели: что происходит, почему так решили и как починить."""

    target: str
    host: str
    kind: str
    title: str
    severity: str
    confidence: float
    summary: str
    evidence: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    channel: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "host": self.host,
            "kind": self.kind,
            "title": self.title,
            "severity": self.severity,
            "confidence": round(self.confidence, 2),
            "summary": self.summary,
            "evidence": list(self.evidence),
            "fixes": list(self.fixes),
            "commands": list(self.commands),
            "channel": self.channel,
        }


@dataclass
class AvailabilityReport:
    ts: str
    status: str            # ok | degraded | blocked | down | unknown
    summary: str
    targets: list[TargetSnapshot] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    vantage: dict[str, Any] = field(default_factory=dict)
    duration_sec: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def worst_severity(self) -> str:
        if not self.verdicts:
            return "info"
        return min((v.severity for v in self.verdicts), key=lambda s: SEVERITY_ORDER.get(s, 9))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "status": self.status,
            "summary": self.summary,
            "duration_sec": round(self.duration_sec, 2),
            "worst_severity": self.worst_severity(),
            "warnings": list(self.warnings),
            "vantage": dict(self.vantage),
            "verdicts": [v.to_dict() for v in self.verdicts],
            "targets": [t.to_dict() for t in self.targets],
        }
