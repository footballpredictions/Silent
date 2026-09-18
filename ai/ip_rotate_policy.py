"""Смена публичного IP VPS: план + OneDash-инвентарь, без платного вызова и без wdtt.

Улей и соты 1–3 в кабинете OneDash (API 2.0). В публичных доках нет change-ip;
POST не вызывается. Дефолт — dry-run, executed всегда False.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ai.availability_knowledge import KIND_IP_BLACKHOLE, KIND_PORT_BLOCK
from ai.availability_model import TARGET_CELL, TARGET_QUEEN, TargetSnapshot, Verdict

ACTION_HOLD = "hold"
ACTION_DRY_RUN = "dry_run"

HOSTER_ONEDASH = "onedash"
HOSTER_HOSTKEY = "hostkey"

# Карта читателей из TECHNOLOGY.md. Пропуск любого ломает вход или деплой.
IP_READERS: tuple[tuple[str, str], ...] = (
    ("hive_cells.public_ip / api_url", "/config, управление сотами, мониторинг"),
    ("тема hive_standby_api_urls", "прогретые клиенты"),
    ("CELL_PUBLIC_IP env агента", "status/provision соты"),
    ("HIVE_QUEEN_IP / HIVE_API_URL на всех сотах", "прокси, health, SMTP"),
    ("DNAT/WDTT_API 10.66.66.1:8000", "туннель жив, API недоступен"),
    ("DEPLOY_HOST / jump / known_hosts", "деплой и recovery"),
    ("nip.io, DNS, SAN/certs/nginx", "TLS и ссылки"),
    ("firewall / security group / host routes", "новый IP недоступен или лишний доступ"),
    ("WG/WDTT Endpoint и кеш config", "живые сессии не мигрируют сами"),
    ("baked seeds Android/PC/iOS/OpenWrt", "холодный старт не знает новый API"),
    ("bootstrap overlay endpoint", "нет регистрации до основного VPN"),
    ("verification/reset/payment URLs", "старые письма и callbacks"),
    ("SMTP relay allowlists", "регистрация есть, письма нет"),
    ("monitoring inventory", "пробы старого IP крутят ротацию"),
    ("PTR/rDNS и AI-exit", "репутация не следует за адресом"),
)

KNOWN_HOSTER_BY_IP = {
    "89.125.188.100": HOSTER_ONEDASH,  # Улей, vps 167346 ams
    "87.58.213.193": HOSTER_ONEDASH,  # Сота 1, vps 231323 hel
    "78.17.74.27": HOSTER_ONEDASH,  # Сота 2, vps 231324 fra
    "192.177.26.38": HOSTER_ONEDASH,  # Сота 3, vps 315445 nyc (ASN мог быть HOSTKEY)
}

# Сверка GET /api/vps 2026-09-18. После реальной смены IP устареет.
ONEDASH_VPS_BY_IP = {
    "89.125.188.100": 167346,
    "87.58.213.193": 231323,
    "78.17.74.27": 231324,
    "192.177.26.38": 315445,
}

MAX_REPLACEMENTS_24H = 1
CONFIRM_PATH_FAILURES = 3


@dataclass(frozen=True)
class IpRotateInput:
    node_id: str
    node_name: str
    current_ip: str
    role: str
    hoster_id: str = ""
    change_ip_method: str = ""
    vps_id: int | None = None
    dry_run: bool = True
    paid_enabled: bool = False
    allowlist: tuple[str, ...] = ()
    rf_coverage_ok: bool = False
    service_healthy: bool = True
    path_failures: int = 0
    replacements_24h: int = 0
    budget_known: bool = False
    max_price: float | None = None
    blocking_kind: str = ""


@dataclass
class IpRotateDecision:
    action: str = ACTION_HOLD
    reason: str = ""
    title: str = ""
    node_id: str = ""
    current_ip: str = ""
    hoster_id: str = ""
    vps_id: int | None = None
    executed: bool = False
    readers: list[dict[str, str]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "title": self.title,
            "node_id": self.node_id,
            "current_ip": self.current_ip,
            "hoster_id": self.hoster_id,
            "vps_id": self.vps_id,
            "executed": False,
            "readers": list(self.readers),
            "notes": list(self.notes),
        }


def hoster_for_ip(ip: str) -> str:
    return KNOWN_HOSTER_BY_IP.get((ip or "").strip(), "")


def vps_id_for_ip(ip: str) -> int | None:
    return ONEDASH_VPS_BY_IP.get((ip or "").strip())


def readers_checklist() -> list[dict[str, str]]:
    return [{"resource": name, "if_missed": miss} for name, miss in IP_READERS]


def decide_ip_rotate(inp: IpRotateInput) -> IpRotateDecision:
    """Никогда не вызывает API хостера. Платная замена только при явном paid_enabled."""
    notes = [
        "Платная смена IP не вызывается из этого модуля.",
        "wdtt не рестартить. Ключи WG и слоты не менять.",
        "Автосмен не смотрит на «80% уверенности» классификатора.",
    ]
    hoster = inp.hoster_id or hoster_for_ip(inp.current_ip)
    if hoster == HOSTER_ONEDASH and not inp.change_ip_method:
        notes.append(
            "OneDash API 2.0: метода смены IP в публичных доках нет "
            "(https://github.com/OneDashRDP/api-docs). POST не вызываем."
        )
    base = IpRotateDecision(
        action=ACTION_HOLD,
        node_id=inp.node_id,
        current_ip=inp.current_ip,
        hoster_id=hoster,
        vps_id=inp.vps_id or vps_id_for_ip(inp.current_ip),
        executed=False,
        readers=readers_checklist(),
        notes=notes,
    )
    if inp.allowlist and inp.node_id not in inp.allowlist and inp.current_ip not in inp.allowlist:
        base.reason = "not_allowlisted"
        base.title = "IP не в allowlist владельца"
        return base
    if not inp.service_healthy:
        base.reason = "service_unhealthy"
        base.title = "Сервис на ноде нездоров — сначала чинить, не покупать IP"
        return base
    if not inp.rf_coverage_ok:
        base.reason = "no_rf_coverage"
        base.title = "Нет пригодных проб из РФ — автоматическая покупка запрещена"
        return base
    if inp.path_failures < CONFIRM_PATH_FAILURES:
        base.reason = "not_confirmed"
        base.title = "Путь не подтверждён несколькими прогонами"
        return base
    if inp.replacements_24h >= MAX_REPLACEMENTS_24H:
        base.reason = "daily_limit"
        base.title = "Лимит замен на ноду за 24ч"
        return base
    if not inp.budget_known or inp.max_price is None:
        base.reason = "budget_unknown"
        base.title = "Цена/бюджет неизвестны — стоп"
        return base
    if not base.hoster_id:
        base.reason = "hoster_unknown"
        base.title = "Хостер этой ноды не установлен, API смены IP нет"
        notes.append("Сота 3 HOSTKEY известна по ASN; Улей и соты 1/2 — OneDash.")
        return base
    if hoster == HOSTER_ONEDASH and not inp.change_ip_method:
        base.action = ACTION_DRY_RUN
        base.reason = "change_ip_not_in_api_docs"
        base.title = "OneDash: смена IP только в кабинете, в API 2.0 метода нет"
        return base
    if not inp.paid_enabled or inp.dry_run:
        base.action = ACTION_DRY_RUN
        base.reason = "dry_run"
        base.title = f"Dry-run смены IP {inp.current_ip} ({base.hoster_id})"
        notes.append("Владелец должен явно включить paid_enabled и снять dry_run.")
        return base
    # Сюда не попадаем при дефолтных настройках. Всё равно не исполняем.
    base.action = ACTION_DRY_RUN
    base.reason = "paid_blocked_in_code"
    base.title = "Платный вызов хостера в коде отключён"
    notes.append("Адаптер OneDash есть, но POST смены IP заблокирован.")
    return base


def build_ip_plan(
    targets: list[TargetSnapshot],
    verdicts: list[Verdict] | None = None,
    *,
    dry_run: bool = True,
    paid_enabled: bool = False,
    allowlist: tuple[str, ...] = (),
) -> dict:
    """Карточка для отчёта доступности. executed всегда False."""
    verdicts = verdicts or []
    by_host = {v.host: v for v in verdicts if v.kind in (KIND_IP_BLACKHOLE, KIND_PORT_BLOCK)}
    queen = next((t for t in targets if t.role == TARGET_QUEEN), None)
    snap = queen or next((t for t in targets if t.role == TARGET_CELL and not t.ai_exit), None)
    if snap is None:
        return {}
    blocking = by_host.get(snap.host)
    decision = decide_ip_rotate(
        IpRotateInput(
            node_id=snap.host,
            node_name=snap.name,
            current_ip=snap.host,
            role=snap.role,
            hoster_id=hoster_for_ip(snap.host),
            vps_id=vps_id_for_ip(snap.host),
            dry_run=dry_run,
            paid_enabled=paid_enabled,
            allowlist=allowlist,
            rf_coverage_ok=bool(snap.ru_channels()),
            service_healthy=True,
            path_failures=CONFIRM_PATH_FAILURES if blocking else 0,
            replacements_24h=0,
            budget_known=False,
            blocking_kind=blocking.kind if blocking else "",
        )
    )
    data = decision.to_dict()
    data["explain"] = (
        "Смена публичного IP — платная операция хостера, не failover :9100. "
        "OneDash: чтение VPS разрешено, POST change-ip в API 2.0 нет."
    )
    return data
