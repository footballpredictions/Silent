"""Unit: базовая гигиена соты не роняет VPN и не закрывает лишнего.

Сеть не трогаем — проверяем сгенерированный bash и его попадание в провижининг.
Запуск: python scripts/test_cell_hardening_unit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.cell_hardening import (  # noqa: E402
    HARDEN_ROOT,
    HARDEN_UNIT,
    baseline_setup_block,
    harden_script,
)

PROVISION_SRC = (ROOT / "app" / "services" / "hive_provision_service.py").read_text(encoding="utf-8")


def test_old_clients_keep_their_ports() -> None:
    """56000/56001 и SSH обязаны остаться открытыми — на них живут 1.0.160/1.0.161."""
    s = baseline_setup_block()
    for rule in ("ufw allow 22/tcp", "ufw allow 56000/udp", "ufw allow 56001/udp"):
        assert rule in s, f"пропало разрешение: {rule}"
    assert "ufw allow 9100/tcp" in s, "cell-agent — запасной API клиентов, снаружи не закрываем"
    assert "ufw allow from 10.66.0.0/16" in s, "клиентам из туннеля нужен доступ к соте"


def test_forward_policy_set_before_enable() -> None:
    """ufw с DROP в FORWARD убивает транзит клиентов — ACCEPT ставится раньше enable."""
    s = baseline_setup_block()
    assert 'DEFAULT_FORWARD_POLICY="ACCEPT"' in s
    assert s.index("DEFAULT_FORWARD_POLICY") < s.index("ufw --force enable")


def test_enable_is_idempotent() -> None:
    """Повторный прогон не должен перезаливать ufw: enable только из inactive."""
    s = baseline_setup_block()
    assert "grep -qi inactive" in s
    assert s.count("ufw --force enable") == 1


def test_wdtt_is_never_touched() -> None:
    for s in (baseline_setup_block(), harden_script()):
        assert "wdtt" not in s, "wdtt не рестартим и не трогаем (vpn-safety)"
        assert "systemctl restart" not in s
        assert "iptables -F" not in s and "iptables -X" not in s


def test_ttl_and_ipv6() -> None:
    s = baseline_setup_block()
    assert "--ttl-set 64" in s
    assert "ip6tables -A FORWARD -j DROP" in s
    assert "precedence ::ffff:0:0/96  100" in s
    # ipv6_mode=keep: правки IPv6 и gai.conf отключены сравнением, которое в bash всегда ложно.
    keep = baseline_setup_block(ipv6_mode="keep")
    assert 'IPV6_MODE="keep"' in keep
    assert 'if [ "keep" = "off" ]' in keep
    assert 'if [ "off" = "off" ]' in s


def test_rules_survive_reboot() -> None:
    s = baseline_setup_block()
    assert f"/etc/systemd/system/{HARDEN_UNIT}.service" in s
    assert f"systemctl enable {HARDEN_UNIT}" in s
    assert "After=network-online.target ufw.service" in s, "ufw перезаливает цепочки — идём после него"
    assert f"{HARDEN_ROOT}/10-baseline.sh" in s


def test_ai_profile_reapplied_after_baseline() -> None:
    """На ИИ-соте правила строже: после базовых их надо переиграть, а не оставить сорванными."""
    s = baseline_setup_block()
    assert "/opt/silent-vpn/ai-exit/10-hygiene.sh" in s
    # Скрипт запускается в конце блока — уже после ufw, который перезаливает цепочки.
    assert s.index("ufw --force enable") < s.rindex(f"{HARDEN_ROOT}/10-baseline.sh")


def test_bad_input_rejected() -> None:
    for kwargs in ({"agent_port": 0}, {"vpn_net": "10.66.0.0"}, {"ipv6_mode": "как-нибудь"}):
        try:
            baseline_setup_block(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"пропустили мусорный аргумент: {kwargs}")


def test_provisioning_runs_hardening_before_nat() -> None:
    """Гигиена должна встать в скрипт подключения соты и до правил nat."""
    assert "baseline_setup_block" in PROVISION_SRC
    assert "{hardening}" in PROVISION_SRC
    assert PROVISION_SRC.index("{hardening}") < PROVISION_SRC.index('echo "[hive] net..."')
    assert "ufw allow 56000/udp 2>/dev/null" not in PROVISION_SRC, "старые ufw-строки заменены блоком"


def test_harden_script_is_self_contained() -> None:
    s = harden_script()
    assert s.startswith("set -u")
    assert "=== done ===" in s, "раннер ждёт этот маркер"


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
        print(f"ok  {fn.__name__}")
    print("ok")
