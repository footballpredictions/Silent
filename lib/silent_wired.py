"""Wi-Fi vs ethernet ifname heuristics for Silent UI (cable-only login)."""

from __future__ import annotations


def is_wireless_ifname(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    if n in {"br-lan", "lan", "eth0", "eth1"}:
        return False
    if n.startswith("lan") and n[3:].isdigit():
        return False
    if n.startswith("wlan") or n.startswith("apcli") or n.startswith("rax"):
        return True
    if n.startswith("ra") and n[2:].isdigit():
        return True
    if n.startswith("wl") and n[2:].isdigit():
        return True
    if n.startswith("ath") and n[3:].isdigit():
        return True
    if "-ap" in n and n.startswith("phy"):
        return True
    return False
