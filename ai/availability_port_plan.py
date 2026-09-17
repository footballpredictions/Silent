"""План запасного порта API: решение + текст для админки.

Решение считает `hive_api_port_policy.decide_api_port_action`. Публикацию в тему
делает `hive_api_port_exec` (агент вызывает после плана). 443/22/wdtt не закрываем.

Чистые функции: без сети, БД и iptables.
"""
from __future__ import annotations

from ai.availability_model import (
    CHANNEL_API_HTTP,
    CHANNEL_API_TCP,
    CHANNEL_API_TLS,
    CHANNEL_PING,
    TargetSnapshot,
)
from ai.hive_api_port_policy import (
    ACTION_CLOSE_STALE_ALT,
    ACTION_HOLD,
    ACTION_OPEN_CANDIDATE,
    CANDIDATE_ORDER,
    PortPolicyInput,
    PortPolicyDecision,
    decide_api_port_action,
)

# Объяснение для админки: почему агент не крутит порт прямо сейчас.
REASON_TEXT = {
    "local_443_down": "Локально 443 не отвечает — это наша поломка, а не блокировка. Порт менять нельзя.",
    "ip_blackhole": "IP заглушен целиком (молчит и ping) — новый порт на том же адресе не поможет.",
    "partial_or_ok": "С РФ API проходит со всех нод — запасной порт не нужен.",
    "not_all_failed": "Мертвы не все каналы API — ждём подтверждения.",
    "unconfirmed": "Канал мёртв, но подтверждённых окон пока мало.",
    "dry_run": "Блок есть, кандидат найден. Автосмена выключена — порт не открываем.",
    "no_candidate": "Блок есть, но живого кандидата с РФ нет: все кандидаты в таймаут.",
    "confirmed_port_block": "Блок подтверждён — открываем запасной порт в теме.",
    "rf_block": "С РФ часть нод режет 443. Публикуем запасной порт; 443 не закрываем — старые клиенты остаются на нём.",
    "already_open": "Запасной порт уже опубликован в теме — второй не открываем.",
    "stale_alt": "Ранее открытый запасной порт умер, есть живая замена — старый можно закрыть.",
}


def api_channel_counts(snap: TargetSnapshot) -> dict[str, int]:
    """TCP/TLS/ping с российских нод — вход для политики."""
    out = {"tcp_ok": 0, "tcp_fail": 0, "tls_ok": 0, "tls_fail": 0, "ping_ok": 0, "ping_fail": 0}
    for channel, prefix in ((CHANNEL_API_TCP, "tcp"), (CHANNEL_API_TLS, "tls"), (CHANNEL_PING, "ping")):
        agg = snap.ru_view(channel)
        if agg is None:
            continue
        out[f"{prefix}_ok"] = agg.ok_count
        out[f"{prefix}_fail"] = agg.fail_count
    return out


def local_api_ok(snap: TargetSnapshot) -> bool:
    """Улей сам себя видит на 443: иначе это service_down, а не блокировка."""
    for channel in (CHANNEL_API_TCP, CHANNEL_API_TLS, CHANNEL_API_HTTP):
        probe = snap.local.get(channel)
        if probe is not None and probe.ok:
            return True
    return False


def api_tcp_dead(counts: dict[str, int]) -> bool:
    """Окно мёртвое: ни одного успешного TCP с РФ, а попытки были."""
    return counts.get("tcp_ok", 0) == 0 and counts.get("tcp_fail", 0) > 0


def next_all_failed_streak(previous: int, counts: dict[str, int]) -> int:
    """Счётчик подряд мёртвых окон. Любой успешный TCP обнуляет — иначе флап накопится."""
    if not api_tcp_dead(counts):
        return 0
    return max(0, int(previous)) + 1


def policy_input(
    snap: TargetSnapshot,
    *,
    consecutive_all_failed: int,
    published_alt_ports: tuple[int, ...] = (),
    stale_alt_blocked: tuple[int, ...] = (),
    candidate_reach: dict[str, str] | None = None,
    confirm_cycles: int = 3,
    alt_grace_cycles: int = 0,
    autoswitch: bool = False,
) -> PortPolicyInput:
    counts = api_channel_counts(snap)
    return PortPolicyInput(
        **counts,
        local_443_ok=local_api_ok(snap),
        consecutive_all_failed=max(0, int(consecutive_all_failed)),
        confirm_cycles=max(1, int(confirm_cycles)),
        autoswitch=bool(autoswitch),
        open_ports=(snap.api_port or 443,) + tuple(published_alt_ports),
        published_alt_ports=tuple(published_alt_ports),
        alt_grace_cycles=max(0, int(alt_grace_cycles)),
        stale_alt_blocked=tuple(stale_alt_blocked),
        candidate_reach=dict(candidate_reach or {}),
    )


def needs_candidate_probe(counts: dict[str, int], streak: int, *, confirm_cycles: int = 3) -> bool:
    """Кандидатов зовём при любой резке с РФ, в том числе 1/2."""
    del streak, confirm_cycles
    return int(counts.get("tcp_fail", 0) or 0) > 0 or int(counts.get("tls_fail", 0) or 0) > 0


def plan_to_dict(
    decision: PortPolicyDecision,
    *,
    streak: int,
    autoswitch_enabled: bool,
    candidate_reach: dict[str, str] | None = None,
) -> dict:
    """Готовая карточка для админки: действие, порт, объяснение, что пробовали."""
    reach = dict(candidate_reach or {})
    if decision.action == ACTION_OPEN_CANDIDATE:
        title = f"Открыть запасной порт {decision.port}"
    elif decision.action == ACTION_CLOSE_STALE_ALT:
        title = f"Закрыть мёртвый запасной порт {decision.close_port}"
    elif decision.reason == "already_open" and decision.suggested_port:
        title = f"Запасной порт {decision.suggested_port} опубликован"
    elif decision.suggested_port:
        title = f"Держать 443; кандидат {decision.suggested_port}"
    else:
        title = "Держать 443"
    return {
        "action": decision.action,
        "title": title,
        "port": decision.port,
        "suggested_port": decision.suggested_port,
        "close_port": decision.close_port,
        "keep_open": list(decision.keep_open),
        "reason": decision.reason,
        "explain": REASON_TEXT.get(decision.reason, decision.reason),
        "dead_windows": max(0, int(streak)),
        "autoswitch": bool(autoswitch_enabled),
        "executed": False,  # агент выставит True после публикации в тему
        "candidates": [
            {"port": p, "ru": reach.get(str(p), reach.get(p, "не проверяли"))}
            for p in CANDIDATE_ORDER
        ],
    }


def build_plan(
    snap: TargetSnapshot,
    *,
    previous_streak: int,
    published_alt_ports: tuple[int, ...] = (),
    stale_alt_blocked: tuple[int, ...] = (),
    candidate_reach: dict[str, str] | None = None,
    confirm_cycles: int = 3,
    autoswitch_enabled: bool = False,
) -> tuple[dict, int]:
    """Карточка плана + новый счётчик мёртвых окон. На хосте ничего не меняет."""
    counts = api_channel_counts(snap)
    streak = next_all_failed_streak(previous_streak, counts)
    inp = policy_input(
        snap,
        consecutive_all_failed=streak,
        published_alt_ports=published_alt_ports,
        stale_alt_blocked=stale_alt_blocked,
        candidate_reach=candidate_reach,
        confirm_cycles=confirm_cycles,
        autoswitch=autoswitch_enabled,
    )
    decision = decide_api_port_action(inp)
    plan = plan_to_dict(
        decision,
        streak=streak,
        autoswitch_enabled=autoswitch_enabled,
        candidate_reach=candidate_reach,
    )
    return plan, streak


__all__ = [
    "ACTION_HOLD",
    "api_channel_counts",
    "api_tcp_dead",
    "build_plan",
    "local_api_ok",
    "needs_candidate_probe",
    "next_all_failed_streak",
    "plan_to_dict",
    "policy_input",
]
