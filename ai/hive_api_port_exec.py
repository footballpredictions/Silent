"""Публикация запасного HTTPS-порта Улья в тему. Без iptables, ufw, wdtt.

Nginx уже слушает 2083 (docker/nginx.conf). Исполнитель только пишет порт в
файл на volume `static/` — API читает его на каждом запросе темы, recreate
не нужен. 443/22/80/8000/56000/56001 никогда не пишем и не снимаем.
"""
from __future__ import annotations

import os
from pathlib import Path

from ai.hive_api_port_policy import FORBIDDEN_PORTS, KEEP_FOREVER

DEFAULT_RUNTIME_FILE = "/app/static/.hive_api_alt_ports"


def runtime_alt_ports_path() -> Path:
    raw = (os.environ.get("HIVE_API_ALT_PORTS_FILE") or "").strip()
    return Path(raw or DEFAULT_RUNTIME_FILE)


def parse_ports(raw: str) -> tuple[int, ...]:
    out: list[int] = []
    seen: set[int] = set()
    for part in (raw or "").replace("\n", ",").split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        port = int(part)
        if port <= 0 or port in seen:
            continue
        seen.add(port)
        out.append(port)
    return tuple(out)


def load_published_ports(path: Path | str | None = None) -> tuple[int, ...]:
    p = Path(path) if path is not None else runtime_alt_ports_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return ()
    return parse_ports(raw)


def dump_published_ports(ports: tuple[int, ...] | list[int], path: Path | str | None = None) -> None:
    p = Path(path) if path is not None else runtime_alt_ports_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    keep = [
        int(x)
        for x in ports
        if int(x) > 0 and int(x) not in KEEP_FOREVER and int(x) not in FORBIDDEN_PORTS
    ]
    p.write_text(",".join(str(x) for x in keep) + ("\n" if keep else ""), encoding="utf-8")


def _blocked(port: int) -> str:
    p = int(port)
    if p in KEEP_FOREVER:
        return "keep_forever"
    if p in FORBIDDEN_PORTS:
        return "forbidden"
    return ""


def apply_open_candidate(
    port: int,
    *,
    listening: bool,
    runtime_path: Path | str | None = None,
) -> dict:
    """Добавить порт в тему. Не слушает — не публикуем (регресс мёртвых :2083)."""
    path = Path(runtime_path) if runtime_path is not None else runtime_alt_ports_path()
    published = load_published_ports(path)
    why = _blocked(port)
    if why:
        return {"ok": False, "executed": False, "reason": why, "published": list(published)}
    if not listening:
        return {
            "ok": False,
            "executed": False,
            "reason": "not_listening",
            "published": list(published),
        }
    if port not in published:
        dump_published_ports((*published, int(port)), path)
        published = load_published_ports(path)
    return {"ok": True, "executed": True, "port": int(port), "published": list(published)}


def apply_close_stale_alt(port: int, *, runtime_path: Path | str | None = None) -> dict:
    """Снять запасной порт из темы. 443 и VPN-порты не трогаем."""
    path = Path(runtime_path) if runtime_path is not None else runtime_alt_ports_path()
    published = load_published_ports(path)
    why = _blocked(port)
    if why:
        return {"ok": False, "executed": False, "reason": why, "published": list(published)}
    kept = tuple(p for p in published if p != int(port))
    dump_published_ports(kept, path)
    return {"ok": True, "executed": True, "close_port": int(port), "published": list(kept)}


__all__ = [
    "apply_close_stale_alt",
    "apply_open_candidate",
    "dump_published_ports",
    "load_published_ports",
    "parse_ports",
    "runtime_alt_ports_path",
]
