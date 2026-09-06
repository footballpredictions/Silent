"""Unit: скрипты AI-выхода безопасны для прода (fail-open, wdtt цел, старые клиенты живы).

Сеть не трогаем — проверяем только сгенерированный bash/JSON.
Запуск: python scripts/test_ai_exit_node_unit.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.ai_exit_node import (  # noqa: E402
    AI_DOMAIN_SUFFIXES,
    CLIENT_NET,
    TPROXY_PORT,
    _parse_socks_url,
    audit_script,
    build_phase_script,
    dns_script,
    hygiene_script,
    proxy_script,
    rollback_script,
    singbox_config,
    status_script,
    verify_script,
)

QUEEN = "132.243.234.162"


def _all_scripts() -> dict[str, str]:
    return {
        "audit": audit_script(),
        "hygiene": hygiene_script(queen_ip=QUEEN),
        "dns": dns_script(threat_filter_enabled=True),
        "proxy": proxy_script(),
        "verify": verify_script(),
        "status": status_script(),
        "rollback": rollback_script(scope="all"),
    }


def test_verify_cleans_up_after_itself() -> None:
    """Псевдо-клиент не должен пережить проверку и не должен лезть в реальные адреса."""
    s = verify_script()
    assert "trap cleanup EXIT" in s
    assert s.index("cleanup() {") < s.index("ip netns add")
    assert "10.66.250." in s, "адрес псевдо-клиента вне рабочего диапазона сот"
    assert "ip netns del" in s and "ip link del" in s


def test_vpn_safety_invariants() -> None:
    """Ни один скрипт не роняет wdtt и не закрывает порты старых клиентов."""
    for name, script in _all_scripts().items():
        assert "@@" not in script, f"{name}: остались плейсхолдеры"
        assert script.rstrip().endswith('echo "=== done ==="') or "=== done ===" in script, name
        assert not re.search(r"systemctl\s+(restart|stop|disable|reload)\s+wdtt", script), f"{name}: трогает wdtt"
        code = "\n".join(ln for ln in script.splitlines() if not ln.lstrip().startswith("#"))
        assert "56000" not in code and "56001" not in code, f"{name}: трогает порты старых клиентов"
        # Полный сброс таблиц убил бы правила wdtt/WG на ноде.
        assert not re.search(r"iptables\s+(-t \w+\s+)?-F\s*$", script, re.M), f"{name}: flush всей таблицы"


def test_hygiene_opens_queen_before_closing_port() -> None:
    s = hygiene_script(queen_ip=QUEEN, agent_port=9100)
    allow_at = s.index(f'ufw --force allow from "$QUEEN_IP"')
    delete_at = s.index("ufw --force delete")
    assert allow_at < delete_at, "сначала разрешаем Улью, потом убираем «открыто всем»"
    assert QUEEN in s
    assert '--dport "$AGENT_PORT" -s "$QUEEN_IP" -j ACCEPT' in s
    assert '--dport "$AGENT_PORT" -j DROP' in s
    # SSH сужаем только по явному списку.
    assert 'SSH_ALLOW=""' in s
    assert "22/tcp" in hygiene_script(queen_ip=QUEEN, ssh_allow=["1.2.3.4"])


def test_hygiene_validates_input() -> None:
    for bad in ("", "не-ip", "1.2.3.4; rm -rf /", "example.com"):
        try:
            hygiene_script(queen_ip=bad)
        except ValueError:
            continue
        raise AssertionError(f"пропустили мусорный queen_ip {bad!r}")


def test_dns_only_touches_client_traffic() -> None:
    s = dns_script(threat_filter_enabled=True)
    assert f'-s "$NET"' in s and CLIENT_NET in s
    assert "--dport 53" in s
    # unbound: только IPv4 наружу, DoT, без сторонних резолверов РФ.
    assert "forward-tls-upstream: yes" in s
    assert "do-ip6: no" in s
    assert "77.88.8.8" not in s
    # dnsmasq с filter-AAAA, но с проверкой поддержки — иначе резолвер клиентов умрёт.
    assert "filter-AAAA" in s
    assert "dnsmasq --test" in s
    assert 'write_dnsmasq ""' in s
    # Список угроз подключаем только когда фильтр включён в админке.
    assert 'if [ "on" = "on" ]' in s and "tif.dnsmasq" in s
    off = dns_script(threat_filter_enabled=False)
    assert 'if [ "off" = "on" ]' in off
    assert "rm -f /etc/silent-ai/tif.dnsmasq" in off


def test_proxy_is_fail_open() -> None:
    s = proxy_script()
    # Цепочку в PREROUTING вешает только watchdog и только если sing-box жив.
    assert s.count("iptables -t mangle -A PREROUTING") == 1
    assert 'hook_present || iptables -t mangle -A PREROUTING -s "$NET" -j "$CHAIN"' in s
    assert "if healthy; then install_rules; else remove_hook; fi" in s
    assert "[ -f /etc/silent-ai/proxy.enabled ] || return 1" in s
    # Конфиг проверяем до того, как что-то менять.
    assert s.index("sing-box check") < s.index("watchdog.sh")
    # Ресурсы ограничены, чтобы прокси не задушил ноду.
    assert "MemoryMax=512M" in s and "CPUQuota=150%" in s
    # Перехватываем только клиентский HTTP/HTTPS.
    assert '--dports 80,443 -j TPROXY --on-port "$PORT"' in s
    assert f"s|__NET__|{CLIENT_NET}|" in s, "watchdog должен работать только с клиентской сетью"
    # Выключенный прокси = выключенный переключатель.
    assert "rm -f /etc/silent-ai/proxy.enabled" in proxy_script(enable=False)


def test_singbox_config_shape() -> None:
    cfg = singbox_config()
    assert cfg["route"]["final"] == "direct"
    assert cfg["inbounds"][0]["type"] == "tproxy"
    assert cfg["inbounds"][0]["listen_port"] == TPROXY_PORT
    assert cfg["inbounds"][0]["sniff"] is True
    tags = {o["tag"] for o in cfg["outbounds"]}
    assert {"direct", "ai-out", "block"} <= tags
    ai_out = next(o for o in cfg["outbounds"] if o["tag"] == "ai-out")
    assert ai_out["type"] == "direct", "без цепочки ИИ-домены идут напрямую с ноды"
    suffixes = cfg["route"]["rules"][-1]["domain_suffix"]
    for must in ("chatgpt.com", "gemini.google.com", "claude.ai"):
        assert must in suffixes
    assert set(suffixes) == set(AI_DOMAIN_SUFFIXES)

    chained = singbox_config(chain_url="socks5://u:p@203.0.113.9:1080")
    ai_out = next(o for o in chained["outbounds"] if o["tag"] == "ai-out")
    assert ai_out["type"] == "socks"
    assert ai_out["server"] == "203.0.113.9" and ai_out["server_port"] == 1080
    assert ai_out["username"] == "u"
    # Цепочка — только для ИИ-доменов, остальное всегда direct.
    assert chained["route"]["final"] == "direct"

    # Секреты цепочки не должны утечь в git: они появляются только в скрипте.
    s = proxy_script(chain_url="socks5://u:p@203.0.113.9:1080")
    assert "chmod 600 /etc/silent-ai/sing-box.json" in s


def test_warp_chain_is_opt_in_and_patched_on_node() -> None:
    cfg = singbox_config(chain_url="warp")
    ai_out = next(o for o in cfg["outbounds"] if o["tag"] == "ai-out")
    assert ai_out["type"] == "wireguard"
    # Ключи WARP появляются только на ноде, в репозитории их быть не должно.
    assert ai_out["private_key"] == "__WARP_PRIVATE_KEY__"
    s = proxy_script(chain_url="warp")
    assert 'if [ "warp" = "warp" ]' in s
    assert "wgcf register --accept-tos" in s
    # Патчим конфиг до sing-box check, иначе поднимем заведомо битый прокси.
    assert s.index("wgcf-profile.conf") < s.index("sing-box check")
    # Без цепочки блок WARP не выполняется.
    assert 'if [ "direct" = "direct" ]' not in proxy_script()
    assert 'if [ "warp" = "warp" ]' not in proxy_script()


def test_chain_url_validation() -> None:
    for bad in ("http://host:1080", "socks5://host", "просто мусор"):
        try:
            _parse_socks_url(bad)
        except ValueError:
            continue
        raise AssertionError(f"пропустили мусорную цепочку {bad!r}")


def test_rollback_order_and_scope() -> None:
    s = rollback_script(scope="all")
    assert s.index("TPROXY снят") < s.index("DNS-заворот снят") < s.index("гигиена откачена")
    assert "ufw --force allow" in s, "cell-agent должен вернуться наружу"
    # Ранний выход по scope стоит до DNS и до гигиены.
    assert s.index('if [ "$SCOPE" = "proxy" ]') < s.index("DNS-заворот снят")
    assert s.index('if [ "$SCOPE" = "dns" ]') < s.index("гигиена откачена")
    assert 'SCOPE="proxy"' in rollback_script(scope="proxy")
    assert 'SCOPE="dns"' in rollback_script(scope="dns")
    try:
        rollback_script(scope="всё подряд")
    except ValueError:
        pass
    else:
        raise AssertionError("неизвестный scope должен падать")


def test_build_phase_dispatch() -> None:
    assert build_phase_script("audit") == audit_script()
    assert "QUEEN_IP" in build_phase_script("hygiene", queen_ip=QUEEN)
    try:
        build_phase_script("что-то своё")
    except ValueError:
        pass
    else:
        raise AssertionError("неизвестная фаза должна падать")


def test_singbox_config_is_valid_json_in_script() -> None:
    s = proxy_script()
    body = s.split("<<'SBEOS'\n", 1)[1].split("\nSBEOS", 1)[0]
    json.loads(body)


if __name__ == "__main__":
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
        print(f"ok  {fn.__name__}")
    print("ok")
