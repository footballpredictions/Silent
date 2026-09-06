"""Security events from trusted admin IPs must not pollute hive incidents."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from app.services.hive_incidents import (  # noqa: E402
    clear_incidents,
    is_trusted_admin_client,
    list_incidents,
    push_security_event,
    remember_trusted_admin_ip,
    set_trusted_admin_ips,
)


def test_trusted_ip_skips_security_event():
    clear_incidents()
    set_trusted_admin_ips(["203.0.113.10"])
    assert is_trusted_admin_client("203.0.113.10")
    assert is_trusted_admin_client("10.66.66.5")
    assert is_trusted_admin_client("172.18.0.1")
    assert not is_trusted_admin_client("198.51.100.7")

    assert push_security_event(
        source="admin-host-guard",
        message="AdminHostGuard blocked forbidden host",
        client_ip="172.18.0.1",
        details="path=/ host=132.243.234.162",
    ) is False
    assert list_incidents(10) == []

    assert push_security_event(
        source="admin-host-guard",
        message="AdminHostGuard blocked forbidden host",
        client_ip="203.0.113.10",
        details="path=/ host=evil.example",
    ) is False
    assert list_incidents(10) == []

    assert push_security_event(
        source="admin-host-guard",
        message="AdminHostGuard blocked forbidden host",
        client_ip="198.51.100.7",
        details="path=/ host=evil.example",
    ) is True
    items = list_incidents(10)
    assert len(items) == 1
    assert "198.51.100.7" in items[0]["message"]


def test_remember_extends_trusted_set():
    clear_incidents()
    set_trusted_admin_ips([])
    remember_trusted_admin_ip("198.51.100.20")
    assert is_trusted_admin_client("198.51.100.20")
    assert (
        push_security_event(
            source="mfa",
            message="bad_code",
            client_ip="198.51.100.20",
        )
        is False
    )


if __name__ == "__main__":
    test_trusted_ip_skips_security_event()
    test_remember_extends_trusted_set()
    print("ok")
