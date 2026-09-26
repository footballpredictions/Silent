"""Unit: Улей пушит свой IP на соты."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault("app.database", SimpleNamespace(AsyncSessionLocal=None))

from app.services.hive_queen_push import configure_payload, queen_public_ip  # noqa: E402


def test_configure_payload_lists_siblings():
    body = configure_payload("1.2.3.4", ["http://10.0.0.1:9100", ""])
    assert body["hive_queen_ip"] == "1.2.3.4"
    assert body["sibling_api_urls"] == ["http://10.0.0.1:9100"]


def test_queen_public_ip_parses_only_ipv4():
    assert queen_public_ip("89.125.188.100") == "89.125.188.100"
    assert queen_public_ip("bad") == ""
    assert queen_public_ip("") == ""


if __name__ == "__main__":
    test_configure_payload_lists_siblings()
    test_queen_public_ip_parses_only_ipv4()
    print("ok")
