"""Юнит: egress PMTU/TTL на Улье и соте 3 (без SSH)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.hive_egress_tune import tune_script  # noqa: E402


def test_tcp_mss_clamp_not_raise_mss():
    s = tune_script()
    assert "TCPMSS --clamp-mss-to-pmtu" in s
    assert "--set-mss" not in s
    assert "1460" not in s


def test_does_not_touch_wdtt_or_deny():
    s = tune_script()
    assert not re.search(r"systemctl\s+(restart|stop|disable|reload)\s+wdtt", s)
    assert "56000" not in s and "56001" not in s
    assert not re.search(r"iptables\s+-I\s+FORWARD\s+1\s+-s\s+.*-p\s+udp\s+-j\s+ACCEPT", s)
    assert "SILENT_DENY" not in s or "не обходит" in s.lower() or "не трогаем" in s.lower()
    assert "systemctl is-active wdtt" in s


def test_ttl_ipv6_and_mtu_probing():
    s = tune_script()
    assert "--ttl-set 64" in s
    assert "ip6tables" in s and "FORWARD -j DROP" in s
    assert "tcp_mtu_probing=1" in s
    assert "tcp_slow_start_after_idle=0" in s
    assert "nf_conntrack_udp_timeout=120" in s
    assert "netdev_max_backlog=16384" in s
    assert "99-silent-egress-pmtu.conf" in s
    assert "silent-egress-pmtu.service" in s


if __name__ == "__main__":
    test_tcp_mss_clamp_not_raise_mss()
    test_does_not_touch_wdtt_or_deny()
    test_ttl_ipv6_and_mtu_probing()
    print("ok")
