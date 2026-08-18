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


def node_title_for_slot(slot: str | None) -> str:
    """Подпись ноды для админки: Улей / Сота N (не «Сервер 2»)."""
    n = parse_manual_slot(slot)
    if n == 1 or n is None:
        return "Улей"
    return f"Сота {n - 1}"


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
    wg_live: int = 0,
    wg_live_known: int | None = None,
) -> int:
    """Карточка ноды = онлайн этой ноды из БД (без WG-мусора). wg_* только диагностика."""
    return max(0, int(db_online or 0))
