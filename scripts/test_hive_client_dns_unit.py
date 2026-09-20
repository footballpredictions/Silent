"""Юнит: клиентский DNS Улья → Cloudflare, без рестарта wdtt."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.hive_client_dns import threat_dns_sync_script  # noqa: E402


def test_filter_off_dnat_to_cloudflare_not_yandex():
    s = threat_dns_sync_script()
    assert "1.1.1.1" in s
    assert "SILENT_HIVE_CLIENT_DNS" in s
    assert "enabled=false CF DNAT" in s
    assert "--dport 53" in s
    assert "10.66.0.0/16" in s
    # Яндекс больше не цель DNAT (остаётся только как клиентский wg_dns).
    assert "77.88.8.8" not in s


def test_filter_on_drops_cf_and_uses_gateway():
    s = threat_dns_sync_script()
    assert "10.66.66.1" in s
    assert "SILENT_THREAT_DNS" in s
    assert "del_cf_rules" in s
    assert "enabled=true threat DNAT on, CF off" in s


def test_does_not_touch_wdtt():
    s = threat_dns_sync_script()
    assert not re.search(r"systemctl\s+(restart|stop|disable|reload)\s+wdtt", s)
    assert "56000" not in s and "56001" not in s
    assert "systemctl is-active wdtt" in s
    assert "SILENT_DENY" not in s


if __name__ == "__main__":
    test_filter_off_dnat_to_cloudflare_not_yandex()
    test_filter_on_drops_cf_and_uses_gateway()
    test_does_not_touch_wdtt()
    print("ok")
