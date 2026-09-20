"""Слоты ручного выбора сервера: Улей = server1, Сота N = server{N+1}."""
from __future__ import annotations

import re

_CELL_NUM_RE = re.compile(r"(\d+)", re.IGNORECASE)
_MANUAL_SLOT_RE = re.compile(r"^server(\d+)$")
MANUAL_SERVER_SLOTS = ("server1", "server2", "server3")


def cell_name_number(name: str) -> int | None:
    m = _CELL_NUM_RE.search(name or "")
    return int(m.group(1)) if m else None


def parse_manual_slot(raw: str | None) -> int | None:
    m = _MANUAL_SLOT_RE.match((raw or "").strip().lower())
    return int(m.group(1)) if m else None


def is_manual_server_slot(raw: str | None) -> bool:
    return parse_manual_slot(raw) is not None


def is_manual_server_pin(preferred_server: str | None) -> bool:
    return is_manual_server_slot(preferred_server)


def slot_title(slot: str) -> str:
    n = parse_manual_slot(slot)
    return f"Сервер {n}" if n else (slot or "")


def cell_slot_title(cell, slot: str) -> str:
    """Подпись слота для клиента. Сота с `ai_exit` подписана явно — «Сервер N для ИИ»."""
    base = slot_title(slot)
    if cell is not None and not getattr(cell, "is_queen", False) and getattr(cell, "ai_exit", False):
        return f"{base} для ИИ"
    return base


def node_title_for_slot(slot: str | None) -> str:
    """Подпись ноды для админки: Улей / Сота N (не «Сервер 2»)."""
    n = parse_manual_slot(slot)
    if n == 1 or n is None:
        return "Улей"
    return f"Сота {n - 1}"


def node_title_for_cell(cell) -> str:
    """Подпись живой ноды: Улей или имя/слот соты, не «все на Улье»."""
    if cell is None or getattr(cell, "is_queen", False):
        return "Улей"
    slot = slot_for_cell(cell)
    if slot:
        titled = node_title_for_slot(slot)
        if titled != "Улей":
            return titled
    name = (getattr(cell, "name", None) or "").strip()
    return name or "Сота"


def cell_is_admin_only(cell) -> bool:
    return bool(
        cell is not None
        and not getattr(cell, "is_queen", False)
        and getattr(cell, "admin_only", False)
    )


def cell_selectable_by_user(cell, *, is_admin: bool) -> bool:
    if cell is None:
        return False
    if cell_is_admin_only(cell):
        return bool(is_admin)
    return True


AI_EXIT_MIN_CLIENT = (1, 0, 165)
_CLIENT_VERSION_RE = re.compile(r"(\d+)")


def parse_client_version(raw: str | None) -> tuple[int, int, int] | None:
    parts = [int(x) for x in _CLIENT_VERSION_RE.findall(raw or "")[:3]]
    if not parts:
        return None
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def client_meets_ai_exit_min(app_version: str | None) -> bool:
    parsed = parse_client_version(app_version)
    return parsed is not None and parsed >= AI_EXIT_MIN_CLIENT


def cell_is_ai_exit(cell) -> bool:
    return bool(
        cell is not None
        and not getattr(cell, "is_queen", False)
        and getattr(cell, "ai_exit", False)
    )


def cell_visible_to_client(cell, *, is_admin: bool, app_version: str | None = "") -> bool:
    """Список/выбор: ИИ-слот только с 1.0.165+. Пустая версия = старый клиент.

    ``app_version is None`` — внутренний вызов (не гейтить по версии).
    """
    if not cell_selectable_by_user(cell, is_admin=is_admin):
        return False
    if cell_is_ai_exit(cell) and app_version is not None and not client_meets_ai_exit_min(app_version):
        return False
    return True


def cell_select_forbidden_detail(cell, *, app_version: str | None = "") -> str:
    if cell_is_ai_exit(cell) and app_version is not None and not client_meets_ai_exit_min(app_version):
        return "Сервер доступен начиная с версии 1.0.165"
    return "Сервер временно доступен только администратору"


def slot_for_cell(cell) -> str:
    """Улей = server1, Сота N = server{N+1}. Новые соты → server4+ без правки клиентов."""
    if getattr(cell, "is_queen", False):
        return "server1"
    num = cell_name_number(getattr(cell, "name", "") or "")
    if num is not None and num >= 1:
        return f"server{num + 1}"
    return ""


def device_on_node(
    *,
    cell_is_queen: bool,
    cell_id,
    cell_slot: str,
    device_cell_id,
    preferred: str | None,
) -> bool:
    """К какой ноде относится устройство в админке.

    Default ``server1`` — не ручной пин: если cell_id на соте, устройство на соте.
    Явный pin server2+ важнее устаревшего cell_id.
    """
    pref = (preferred or "").strip().lower()
    pin_n = parse_manual_slot(pref)
    worker_pin = pin_n is not None and pin_n != 1
    if cell_is_queen:
        if worker_pin:
            return False
        return device_cell_id == cell_id or device_cell_id is None
    if cell_slot and pref == cell_slot.lower():
        return True
    if device_cell_id == cell_id and not worker_pin:
        return True
    return False


def assign_online_to_cell_id(
    *,
    device_cell_id,
    preferred: str | None,
    queen_id,
    slot_to_id: dict,
    known_ids: set,
):
    """Каждый онлайн ровно на одной ноде: pin server2+ → сота, иначе cell_id, иначе Улей."""
    pref = (preferred or "").strip().lower()
    pin = parse_manual_slot(pref)
    if pin is not None and pin >= 2:
        cid = slot_to_id.get(f"server{pin}")
        if cid in known_ids:
            return cid
    if device_cell_id in known_ids:
        return device_cell_id
    return queen_id


def node_online_shown(
    *,
    is_queen: bool,
    db_online: int,
    wg_live: int | None = None,
    wg_live_known: int | None = None,
) -> int:
    """Карточка ноды: не прятать людей.

    Агент всегда кладёт ``wg_peers_live_3m`` (часто 0) — из‑за этого соты с
    нагрузкой показывали 0, хотя в БД ``is_connected`` уже есть. Берём максимум
    из БД и живых handshake.
    """
    _ = is_queen
    db = max(0, int(db_online or 0))
    live = 0 if wg_live is None else max(0, int(wg_live))
    known = 0 if wg_live_known is None else max(0, int(wg_live_known))
    return max(db, live, known)


def pick_dashboard_shown_online(
    *,
    ram: int | None,
    shared: int | None,
    stale_ram: int | None,
    soft: bool,
) -> int | None:
    """Одно WG-число для дашборда/шапки при uvicorn --workers 2.

    ram — кэш этого воркера; shared — Redis (общий); stale_ram — просроченный RAM
    только для light-полла. None = нужно обновить по WG live, не брать is_connected из БД.
    """
    if ram is not None:
        return max(0, int(ram))
    if shared is not None:
        return max(0, int(shared))
    if soft and stale_ram is not None:
        return max(0, int(stale_ram))
    return None


def merge_live_wg_pubs(*groups) -> set[str]:
    """Ключи живых handshake с нод (Улей dump + соты /v1/status)."""
    out: set[str] = set()
    for group in groups:
        if not group:
            continue
        for p in group:
            s = str(p).strip()
            if s:
                out.add(s)
    return out


def device_shown_online(device, live_pubs: set[str] | None = None) -> bool:
    """Строка дашборда «онлайн» как шапка: БД или живой WG-ключ устройства.

    ``is_connected`` пишет keepalive. На соте standby глотал /internal/online —
    в БД 9, в шапке 67 (handshake). Сверяем и identity-ключ, и GETCONF extra
    (``wg_live_public_key``), без leftover-счётчика без привязки к устройству.
    """
    if bool(getattr(device, "is_connected", False)):
        return True
    pubs = live_pubs or set()
    if not pubs:
        return False
    for raw in (
        getattr(device, "wg_public_key", None),
        getattr(device, "wg_live_public_key", None),
    ):
        p = (raw or "").strip()
        if p and p in pubs:
            return True
    return False
