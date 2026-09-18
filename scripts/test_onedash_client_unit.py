"""OneDash: только GET, без платного POST, ключ не попадает в ответы."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.onedash_client import (  # noqa: E402
    OneDashClient,
    parse_balance_known,
    parse_vps_items,
)


SAMPLE_VPS = {
    "type": True,
    "data": {
        "items": [
            {
                "id": 20001,
                "order_id": 10001,
                "name": "Hive",
                "active": True,
                "connection": {"host": "89.125.188.100", "port": 22},
                "os": "ubuntu_22",
                "location": "msk",
                "options": {"backup": False, "static_ip": True, "nvme": False},
            }
        ]
    },
}


def test_parse_vps_items_maps_connection_host():
    items = parse_vps_items(SAMPLE_VPS)
    assert len(items) == 1
    assert items[0].vps_id == 20001
    assert items[0].ip == "89.125.188.100"
    assert items[0].static_ip is True


def test_parse_balance_known():
    ok, cur = parse_balance_known({"type": True, "data": {"balance": 10, "currency": "RUB"}})
    assert ok is True
    assert cur == "RUB"
    missing, _ = parse_balance_known({"type": True, "data": {}})
    assert missing is False


def test_client_get_only_rejects_post():
    client = OneDashClient(api_key="k", http=lambda *a, **k: (200, "{}"))
    try:
        client.request("POST", "/api/vps/1/ip")
        raise AssertionError("POST must be rejected")
    except RuntimeError as e:
        assert "запрещён" in str(e)


def test_plan_change_ip_never_executes():
    routes = {
        "/health": (200, '{"ok":true}'),
        "/api/auth/check": (200, '{"type":true}'),
        "/api/balance": (200, json.dumps({"type": True, "data": {"balance": 1, "currency": "RUB"}})),
        "/api/vps?page=1&per_page=100": (200, json.dumps(SAMPLE_VPS)),
        "/api/vps/20001/ip": (404, '{"type":false}'),
        "/api/vps/20001/change-ip": (404, '{"type":false}'),
        "/api/vps/20001/refresh-ip": (404, '{"type":false}'),
        "/api/vps/20001/network": (404, '{"type":false}'),
    }

    def http(url, method, headers, body, timeout):
        assert method in ("GET", "HEAD")
        assert body is None
        path = url.split("https://api.rdp-onedash.ru", 1)[-1]
        status, text = routes.get(path, (404, "{}"))
        return status, text

    client = OneDashClient(api_key="secret-key", http=http)
    plan = client.plan_change_ip("89.125.188.100", dry_run=False, paid_enabled=True, confirm=True)
    assert plan.executed is False
    assert plan.vps_id == 20001
    assert plan.reason == "change_ip_not_in_api_docs"
    assert plan.to_dict()["executed"] is False


def test_missing_ip_is_not_in_account():
    def http(url, method, headers, body, timeout):
        if url.endswith("/api/vps?page=1&per_page=100"):
            return 200, json.dumps(SAMPLE_VPS)
        if url.endswith("/health") or url.endswith("/api/auth/check"):
            return 200, "{}"
        if url.endswith("/api/balance"):
            return 200, json.dumps({"data": {"balance": 0, "currency": "RUB"}})
        return 404, "{}"

    client = OneDashClient(api_key="k", http=http)
    plan = client.plan_change_ip("192.177.26.38")
    assert plan.reason == "vps_not_in_account"
    assert plan.executed is False


def test_key_not_echoed_in_parse_error():
    os.environ["ONEDASH_API_KEY"] = "super-secret-onedash"
    try:
        def http(url, method, headers, body, timeout):
            return 500, "bad super-secret-onedash token"

        client = OneDashClient(http=http)
        status, payload = client.get("/health")
        assert status == 500
        dumped = json.dumps(payload)
        assert "super-secret-onedash" not in dumped
    finally:
        os.environ.pop("ONEDASH_API_KEY", None)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"ok ({len(tests)} tests)")
