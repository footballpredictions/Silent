"""Юнит-тесты инвариантов game-exit (без SSH)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.game_exit_node import (  # noqa: E402
    CLIENT_NET,
    PHASES,
    VERIFY_CLIENT,
    audit_script,
    build_phase_script,
    probe_script,
    rollback_script,
    status_script,
    udp_tune_script,
)


def test_phases_cover_expected() -> None:
    assert set(PHASES) == {"audit", "probe", "udp-tune", "status", "rollback"}


def test_vpn_safety_invariants() -> None:
    scripts = {
        "audit": audit_script(),
        "probe": probe_script(),
        "udp-tune": udp_tune_script(),
        "status": status_script(),
        "rollback": rollback_script(),
    }
    for name, script in scripts.items():
        assert "@@" not in script, f"{name}: остались плейсхолдеры"
        assert "=== done ===" in script, name
        assert not re.search(r"systemctl\s+(restart|stop|disable|reload)\s+wdtt", script), f"{name}: трогает wdtt"
        assert "56000" not in script and "56001" not in script, f"{name}: трогает порты старых клиентов"
        assert not re.search(r"iptables\s+(-t \w+\s+)?-F\s*$", script, re.M), f"{name}: flush всей таблицы"


def test_probe_uses_isolated_netns_and_cleans_up() -> None:
    s = probe_script(relay_limit=8)
    assert "trap cleanup EXIT" in s
    assert s.index("cleanup() {") < s.index("ip netns add")
    assert VERIFY_CLIENT in s
    assert "GetSDRConfig" in s
    assert "appid=570" in s or "570" in s
    assert "STEAM_MTU_RISK" in s or "steam_sizes" in s or "1300" in s


def test_udp_tune_is_idempotent_and_safe_for_deny() -> None:
    s = udp_tune_script()
    assert "nf_conntrack_udp_timeout" in s
    assert "TCPMSS --clamp-mss-to-pmtu" in s
    assert "99-silent-game-exit.conf" in s
    assert "silent-game-exit.service" in s
    assert "systemctl is-active wdtt" in s
    assert "wdtt0 mtu" in s or "mtu 1420" in s or "mtu -> 1420" in s
    # Нельзя ACCEPT UDP в начало FORWARD — обход unpaid deny.
    assert not re.search(r"iptables -I FORWARD 1 -s .* -p udp -j ACCEPT", s)
    assert "-I FORWARD 1 -p icmp" not in s


def test_rollback_removes_rules() -> None:
    s = rollback_script()
    assert "silent-game-exit.service" in s
    assert "99-silent-game-exit.conf" in s
    assert "rm -rf /opt/silent-vpn/game-exit" in s
    assert "SILENT_DENY" not in s or "ipt_del" in s  # rollback чистит старые ACCEPT


def test_build_phase_script() -> None:
    assert "=== mtu ===" in build_phase_script("audit")
    assert "silentgame_verify" in build_phase_script("probe", relay_limit=5)


if __name__ == "__main__":
    test_phases_cover_expected()
    test_vpn_safety_invariants()
    test_probe_uses_isolated_netns_and_cleans_up()
    test_udp_tune_is_idempotent_and_safe_for_deny()
    test_rollback_removes_rules()
    test_build_phase_script()
    print("ok")
