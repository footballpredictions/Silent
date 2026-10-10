"""Один и тот же хеш на Улье и на соте.

Если формулы разъедутся, автоапгрейд видит «чужую» сборку и рестартит
silent-cell-agent каждый цикл. wdtt этот хеш не трогает.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


SHIPPED = (
    "agent_http.py",
    "build_id.py",
    "main.py",
    "standby_online.py",
    "standby_runtime.py",
    "status_cache.py",
)


def agent_build_id(root: Path | None = None) -> str:
    """Хеш только файлов, которые Улей сам заливает.

    Лишний .py на соте (например старый gemini_egress.py) не должен
    делать сборку «чужой» — иначе автоапгрейд рестартит агент каждый цикл.
    """
    folder = root or Path(__file__).resolve().parent
    h = hashlib.sha256()
    for name in SHIPPED:
        path = folder / name
        if not path.is_file():
            continue
        h.update(name.encode("utf-8"))
        h.update(path.read_text(encoding="utf-8").encode("utf-8"))
    return h.hexdigest()[:16]
