"""LAN hostname for the Silent router UI.

Routers use different LAN prefixes (192.168.1.1, 192.168.0.1, 10.0.0.1, …).
The browser URL is always ``{ipv4}.silent.vpn`` and must resolve to that IPv4.
"""

from __future__ import annotations

import re

ZONE = "silent.vpn"
_IPV4 = re.compile(
    r"^(?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d)\."
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\.(?:25[0-5]|2[0-4]\d|1?\d?\d)$"
)


def is_ipv4(value: str) -> bool:
    return bool(_IPV4.match((value or "").strip()))


def lan_host(lan_ip: str) -> str:
    ip = (lan_ip or "").strip()
    if not is_ipv4(ip):
        raise ValueError(f"not an IPv4 LAN address: {lan_ip!r}")
    return f"{ip}.{ZONE}"


def lan_url(lan_ip: str, *, scheme: str = "http") -> str:
    return f"{scheme}://{lan_host(lan_ip)}"


def host_is_silent_zone(host: str) -> bool:
    name = (host or "").split(":", 1)[0].strip().lower().rstrip(".")
    return name == ZONE or name.endswith("." + ZONE)


def dnsmasq_address_lines(lan_ip: str) -> list[str]:
    ip = (lan_ip or "").strip()
    if not is_ipv4(ip):
        raise ValueError(f"not an IPv4 LAN address: {lan_ip!r}")
    host = lan_host(ip)
    return [
        f"address=/{host}/{ip}",
        f"address=/{ZONE}/{ip}",
    ]


def extract_lan_ip_from_host(host: str) -> str | None:
    """If host is ``192.168.1.1.silent.vpn``, return ``192.168.1.1``."""
    name = (host or "").split(":", 1)[0].strip().lower().rstrip(".")
    suffix = "." + ZONE
    if not name.endswith(suffix):
        return None
    maybe_ip = name[: -len(suffix)]
    return maybe_ip if is_ipv4(maybe_ip) else None
