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
