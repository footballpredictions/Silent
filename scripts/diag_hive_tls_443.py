"""Read-only диагностика 443 Улья: TLS живой или отвечает только docker-proxy.

Аудит 2026-09-16 показал `curl https://127.0.0.1/api/health` → 000 при живом
`0.0.0.0:443` (docker-proxy) и рабочем `:80`. Снаружи это выглядит как ТСПУ
(«TCP иногда ok, TLS всегда timeout»), хотя причина может быть внутри: сертификат,
server-блок nginx или мёртвый upstream.

Ничего не рестартит и не меняет: только curl/openssl/логи/конфиг.

    python scripts/diag_hive_tls_443.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_hive_security import connect_flaky  # noqa: E402
from _deploy_common import run  # noqa: E402

DOMAIN = "89-125-188-100.nip.io"

CHECKS: list[tuple[str, str]] = [
    (
        "локальный ответ 80 / 443 / api",
        # Host обязателен: на 443 default_server стоит `return 444`, поэтому запрос
        # с Host=127.0.0.1 закрывается и curl показывает 000 при живом TLS.
        "curl -s -o /dev/null -w 'http80(ip):%{http_code} connect:%{time_connect}\\n' "
        "http://127.0.0.1/api/health --connect-timeout 3 || echo 'http80 FAIL'; "
        f"curl -sk --resolve {DOMAIN}:443:127.0.0.1 -o /dev/null "
        "-w 'https443(host):%{http_code} tls:%{time_appconnect}\\n' "
        f"https://{DOMAIN}/api/health --connect-timeout 4 || echo 'https443 FAIL'; "
        "curl -sk -o /dev/null -w 'https443(ip,ожидаем 000 = return 444):%{http_code}\\n' "
        "https://127.0.0.1/api/health --connect-timeout 3 || true; "
        "curl -s -o /dev/null -w 'api8000:%{http_code}\\n' http://127.0.0.1:8000/health --connect-timeout 3 "
        "|| echo 'api8000 FAIL'",
    ),
    (
        "TLS-рукопожатие на 443",
        "timeout 8 openssl s_client -connect 127.0.0.1:443 -servername 89-125-188-100.nip.io "
        "</dev/null 2>&1 | grep -E 'CONNECTED|subject=|issuer=|Verify return code|no peer|"
        "alert|Cipher is' | head -12 || echo 'openssl: ответа нет'",
    ),
    (
        "сертификаты и срок",
        "for c in /etc/letsencrypt/live/*/fullchain.pem /opt/silent-vpn/backend/certs/*.pem; do "
        "[ -f \"$c\" ] && echo \"== $c\" && openssl x509 -in \"$c\" -noout -subject -enddate 2>/dev/null; "
        "done | head -20",
    ),
    (
        "nginx: слушает ли 443 внутри контейнера",
        "docker exec backend-nginx-1 sh -c 'nginx -T 2>/dev/null | grep -nE \"listen|server_name|ssl_certificate \" "
        "| head -30' || echo 'nginx -T недоступен'",
    ),
    (
        "nginx: последние ошибки",
        "docker logs backend-nginx-1 --since 6h 2>&1 | grep -iE 'emerg|error|ssl|handshake|upstream' "
        "| tail -20 || echo 'ошибок нет'",
    ),
    (
        "docker-proxy 443 → контейнер",
        "docker port backend-nginx-1; "
        "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' backend-nginx-1; "
        "docker exec backend-nginx-1 sh -c 'wget -qO- --timeout=3 http://127.0.0.1/api/health || echo вн_80_FAIL'",
    ),
    (
        "хайрпин на свой публичный IP с правильным Host",
        f"curl -sk -o /dev/null -w 'hairpin443:%{{http_code}} tls:%{{time_appconnect}}\\n' "
        f"--connect-timeout 5 https://{DOMAIN}/api/health || echo 'хайрпин FAIL'",
    ),
]


def main() -> int:
    client = connect_flaky(attempts=40, pause=15)
    try:
        for title, cmd in CHECKS:
            print(f"\n===== {title} =====")
            try:
                run(client, cmd, timeout=90)
            except Exception as e:
                print(f"[skip] {title}: {type(e).__name__}: {e}")
    finally:
        client.close()
    print(
        "\nЧитать так: https443(host) 200 и живое рукопожатие openssl — вход на Улье цел, "
        "недоступность снаружи внешняя. 403 на http80(ip) и 000 на https443(ip) штатные: "
        "allow-list сот и `return 444` для чужого Host. Если же падает именно https443(host) "
        "или openssl не отдаёт сертификат — ломался наш nginx/сертификат."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
