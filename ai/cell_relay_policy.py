"""Dry-run вход→выход: если Сервер 4 режут с РФ, зайти через живую соту.

Как сейчас устроено (и почему «восьмёрка» ещё не в датаплейне):

- API уже кольцо: клиент → Улей:443 → сота:9100 → Улей:80. Сота 3 из этого
  кольца исключена (:9100 закрыт гигиеной ИИ-выхода).
- VPN — нет: клиент получает один Endpoint = публичный IP выбранного сервера.
  У каждой соты свой `wdtt0` и свой шлюз `10.66.66.1`. Между сотами WG нет.
- Если подменить Endpoint на Соту 1 без туннеля Сота1→Сота3, выход станет
  Сотой 1, а не ИИ-выходом. Это хуже, чем «не подключился».

Поэтому модуль только считает маршрут. Исполнитель — отдельный интерфейс
`silent-mesh0` (не `wdtt0`, peer GC Улья его не увидит) + fail-open watchdog
как у AI-exit. `executed` всегда False.

Fail-safe: нет пробы WDTT/WG → сохраняем прямой ход без утверждения доступности. Релей только
когда UDP с РФ точно мёртв, а у входной соты — жив.
"""
from __future__ import annotations

from ai.availability_model import (
    CHANNEL_WDTT_UDP,
    CHANNEL_WG_UDP,
    TARGET_CELL,
    TARGET_QUEEN,
    TargetSnapshot,
)

ACTION_DIRECT = "direct"
ACTION_RELAY = "relay"
ACTION_HOLD = "hold"

EXPLAIN = {
    ACTION_DIRECT: "UDP-проба из РФ прошла. В плане остаётся прямое подключение; полноценная VPN-сессия отдельно не проверялась.",
    ACTION_RELAY: (
        "С РФ цель не отвечает по WDTT/WG, а другая сота жива. Клиенту нужен вход "
        "через неё и отдельный туннель на выход. Туннеля между сотами ещё нет — "
        "маршрут только считаем, wdtt и iptables не трогаем."
    ),
    ACTION_HOLD: "Живого входа с РФ нет — релей некуда ставить. Менять Endpoint нельзя.",
}
UNVERIFIED_DIRECT = (
    "Доступность UDP из РФ не подтверждена: проб нет или данных недостаточно. "
    "Прямой маршрут оставлен по умолчанию; это не результат успешной VPN-проверки."
)


def vpn_path_from_ru(snap: TargetSnapshot) -> bool | None:
    """True = UDP-проба прошла; False = 2+ источника отказа; None = не подтверждено."""
    for channel in (CHANNEL_WDTT_UDP, CHANNEL_WG_UDP):
        agg = snap.ru_view(channel)
        if agg is None:
            continue
        if agg.ok_count:
            return True
        failed_sources = {n.node for n in agg.failing_nodes()}
        return False if len(failed_sources) >= 2 else None
    # ICMP, служебный TCP и молчание UDP не доказывают состояние VPN-канала.
    return None


def _entry_sort_key(snap: TargetSnapshot) -> tuple:
    # Обычная сота (вход API) → Улей → ИИ-выход последним (его не берём как вход).
    if snap.role == TARGET_CELL and not snap.ai_exit:
        return (0, snap.name)
    if snap.role == TARGET_QUEEN:
        return (1, snap.name)
    return (2, snap.name)


def pick_entry(target: TargetSnapshot, snaps: list[TargetSnapshot]) -> TargetSnapshot | None:
    """Первая живая нода, которая не цель и не ИИ-выход (у ИИ :9100 закрыт, это не вход API)."""
    candidates = []
    for snap in snaps:
        if snap is target or snap.host == target.host:
            continue
        if snap.ai_exit:
            continue
        if vpn_path_from_ru(snap) is not True:
            continue
        candidates.append(snap)
    candidates.sort(key=_entry_sort_key)
    return candidates[0] if candidates else None


def _hop(snap: TargetSnapshot, action: str, entry: TargetSnapshot | None = None) -> dict:
    measured = vpn_path_from_ru(snap)
    return {
        "name": snap.name,
        "host": snap.host,
        "ai_exit": bool(snap.ai_exit),
        "action": action,
        "entry": entry.name if entry is not None else (snap.name if action == ACTION_DIRECT else None),
        "exit": snap.name,
        "reason": action,
        "explain": UNVERIFIED_DIRECT if action == ACTION_DIRECT and measured is None else EXPLAIN[action],
        "ru_udp_status": 'unverified' if measured is None else 'reachable' if measured else 'unreachable',
    }


def build_relay_plan(targets: list[TargetSnapshot]) -> dict:
    """Карточка для админки. Ничего не меняет на хостах."""
    snaps = [t for t in targets if t.role in (TARGET_QUEEN, TARGET_CELL)]
    hops: list[dict] = []
    for snap in snaps:
        path = vpn_path_from_ru(snap)
        if path is not False:
            hops.append(_hop(snap, ACTION_DIRECT))
            continue
        entry = pick_entry(snap, snaps)
        if entry is None:
            hops.append(_hop(snap, ACTION_HOLD))
        else:
            hops.append(_hop(snap, ACTION_RELAY, entry))

    interesting = [h for h in hops if h["ai_exit"] or h["action"] != ACTION_DIRECT]
    focus = next((h for h in hops if h["ai_exit"]), hops[0] if hops else None)
    if focus is None:
        title = "Кольца между серверами нет"
        explain = "Нет целей Улей/сота в этом отчёте."
        action = ACTION_HOLD
    else:
        action = str(focus["action"])
        label = 'Сервер 4' if focus['ai_exit'] else focus['name']
        if action == ACTION_RELAY:
            title = f"{label}: вход через {focus['entry']}"
        elif action == ACTION_HOLD:
            title = f"{label}: UDP-пробы не прошли, подтверждённого входа нет"
        elif focus['ru_udp_status'] == 'unverified':
            title = f"{label}: прямой маршрут, UDP не подтверждён"
        else:
            title = f"{label}: UDP-проба прошла, прямой маршрут"
        explain = str(focus["explain"])

    return {
        "action": action,
        "title": title,
        "explain": explain,
        "executed": False,
        "ru_udp_status": focus['ru_udp_status'] if focus else 'unverified',
        "hops": hops,
        "blocked": interesting,
    }


__all__ = [
    "ACTION_DIRECT",
    "ACTION_HOLD",
    "ACTION_RELAY",
    "build_relay_plan",
    "pick_entry",
    "vpn_path_from_ru",
]
