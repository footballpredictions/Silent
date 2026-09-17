"""Порядок запасных API URL: живые соты раньше портов Улья.

Без БД и сети: вызывающий уже отфильтровал AI-соту и собрал списки.
"""
from __future__ import annotations


def compose_standby_api_urls(
    cell_urls: list[str] | tuple[str, ...] = (),
    alt_urls: list[str] | tuple[str, ...] = (),
) -> list[str]:
    """Живые соты :9100 первыми, запасные порты Улья только после них.

    Иначе неопубликованный :2083 съедает слоты писем и таймауты старых клиентов
    (регресс 2026-09-16).
    """
    seen: set[str] = set()
    out: list[str] = []
    for url in (*cell_urls, *alt_urls):
        clean = (url or "").strip().rstrip("/")
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out
