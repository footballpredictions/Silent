"""Server slots 1–4, same merge rule as PC `vpnServerList.ts`."""

from __future__ import annotations

STATIC = (
    ("server1", "Сервер 1"),
    ("server2", "Сервер 2"),
    ("server3", "Сервер 3"),
    ("server4", "Сервер 4 для ИИ"),
)

_ALIASES = {
    "queen": "server1",
    "main": "server1",
    "cell1": "server2",
    "cell2": "server3",
    "cell3": "server4",
    "ai_exit": "server4",
}


def normalize_slot(key: str) -> str:
    k = (key or "").strip().lower()
    return _ALIASES.get(k, k)


def static_vpn_servers() -> list[dict]:
    return [
        {"key": key, "title": title, "public_ip": "", "wdtt_port": 0, "online_count": 0}
        for key, title in STATIC
    ]


def display_vpn_servers(from_api: list[dict] | None = None) -> list[dict]:
    api = list(from_api or [])
    if not api:
        return static_vpn_servers()
    by_key: dict[str, dict] = {}
    for row in api:
        k = normalize_slot(str(row.get("key") or ""))
        if k:
            by_key[k] = {**row, "key": k}
    merged = []
    static_keys = {key for key, _ in STATIC}
    for key, title in STATIC:
        known = by_key.get(key)
        if not known:
            merged.append({"key": key, "title": title, "public_ip": "", "wdtt_port": 0, "online_count": 0})
            continue
        shown = (known.get("title") or "").strip() or title
        if key == "server4" and shown in ("Сервер 4", "server4"):
            shown = title
        merged.append({**known, "key": key, "title": shown})
    for row in api:
        k = normalize_slot(str(row.get("key") or ""))
        if k and k not in static_keys:
            merged.append({**row, "key": k})
    return merged


def selected_title(selected: str, servers: list[dict] | None = None) -> str:
    slot = normalize_slot(selected) or "server1"
    for row in servers or display_vpn_servers(None):
        if row["key"] == slot:
            return row["title"]
    if slot == "server4":
        return "Сервер 4 для ИИ"
    if slot.startswith("server") and slot[6:].isdigit():
        return f"Сервер {slot[6:]}"
    return slot
