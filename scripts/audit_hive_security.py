"""Read-only аудит Улья: вторжение или наш же фаервол режет 443.

Ничего не рестартит, не меняет правила, не трогает wdtt/peer'ы — только читает.
Запуск из папки backend (нужен SSH к Улью; при таймауте публичного :22 берётся
шлюз туннеля 10.66.66.1, то есть VPN должен стоять на слоте Улья):

    python scripts/audit_hive_security.py

Зачем: 2026-09-16 из РФ `:443` и `:22` Улья в таймаут, а `:80` отвечает 403.
Так выглядит и ТСПУ по порту, и наш собственный DROP/ufw. Отличить можно только
изнутри: локальный listen + правила фаервола + счётчики пакетов на 443.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _deploy_common import connect, run  # noqa: E402

CONNECT_ATTEMPTS = 40
CONNECT_PAUSE_SEC = 15


def connect_flaky(attempts: int = CONNECT_ATTEMPTS, pause: int = CONNECT_PAUSE_SEC):
    """Терпеливый SSH: аудит не нужен срочно, а окно открывается через десяток попыток."""
    return connect(timeout=10, attempts=attempts, pause=pause)

# Каждый блок — отдельная команда: один упавший шаг не рвёт весь аудит.
CHECKS: list[tuple[str, str]] = [
    ("хост", "hostname; uptime; date -u"),
    (
        "наш ли DROP на 443/22",
        "ufw status verbose 2>/dev/null | head -25; "
        "echo '--- iptables filter INPUT ---'; "
        "iptables -S INPUT | grep -Ev '^-A (f2b|DOCKER|ufw-(before|after|reject|track))' | head -40; "
        "echo '--- правила про 443/22 ---'; "
        "iptables -S | grep -E 'dport (443|22)\\b' | head -30",
    ),
    (
        "пакеты доходят до 443",
        "iptables -L INPUT -n -v --line-numbers | grep -E 'dpt:(443|22)|Chain' | head -20; "
        "echo '--- conntrack 443 ---'; "
        "(conntrack -L 2>/dev/null | grep -c 'dport=443' || echo 'conntrack нет')",
    ),
    (
        "listen и локальный ответ",
        "ss -lntup | grep -E ':(22|80|443|8000|8443|9100|56000|56001)\\b' || true; "
        "curl -skf -o /dev/null -w 'local443:%{http_code}\\n' https://127.0.0.1/api/health || echo 'local443 FAIL'",
    ),
    (
        "входы SSH",
        "last -n 15 -w 2>/dev/null | head -18; "
        "echo '--- неудачные ---'; "
        "(lastb -n 10 -w 2>/dev/null | head -12 || journalctl -u ssh -n 40 --no-pager | grep -i 'fail' | tail -10); "
        "echo '--- принятые за 7 дней ---'; "
        "(journalctl -u ssh --since '7 days ago' --no-pager 2>/dev/null | grep -c 'Accepted' || true)",
    ),
    (
        "ключи и sshd",
        "for f in /root/.ssh/authorized_keys /home/*/.ssh/authorized_keys; do "
        "[ -f \"$f\" ] && echo \"== $f ($(stat -c %y \"$f\"))\" && cut -c1-80 \"$f\"; done; "
        "echo '--- sshd ---'; "
        "sshd -T 2>/dev/null | grep -E '^(permitrootlogin|passwordauthentication|port|allowusers|listenaddress)' || true",
    ),
    (
        "автозапуск и cron",
        "ls -la /etc/cron.d /etc/cron.hourly 2>/dev/null | head -25; "
        "crontab -l 2>/dev/null | grep -v '^#' | head -15; "
        "echo '--- systemd timers ---'; systemctl list-timers --all --no-pager 2>/dev/null | head -12; "
        "echo '--- unit-файлы за 30 дней ---'; "
        "find /etc/systemd/system -maxdepth 2 -name '*.service' -mtime -30 -printf '%T+ %p\\n' 2>/dev/null | sort | tail -15",
    ),
    (
        "процессы и preload",
        # ps показывает аргументы wdtt-server с -password/-internal-secret: маскируем,
        # иначе секреты прода утекают в лог аудита.
        "ps aux --sort=-%cpu | head -12 | "
        "sed -E 's/(-password|-internal-secret|--password|--token)[= ][^ ]+/\\1 <REDACTED>/g'; "
        "echo '--- ld.so.preload ---'; (cat /etc/ld.so.preload 2>/dev/null || echo 'пусто'); "
        "echo '--- исполняемое в /tmp /dev/shm /var/tmp ---'; "
        "find /tmp /dev/shm /var/tmp -maxdepth 2 -type f -perm -u+x -printf '%T+ %p\\n' 2>/dev/null | tail -15",
    ),
    (
        "docker",
        "docker ps -a --format '{{.Names}}\\t{{.Image}}\\t{{.Status}}' | head -20; "
        "echo '--- images ---'; docker images --format '{{.Repository}}:{{.Tag}}\\t{{.CreatedSince}}' | head -12",
    ),
    (
        "изменения в коде Улья",
        "find /opt/silent-vpn -maxdepth 3 -type f -mtime -7 "
        "-not -path '*/node_modules/*' -not -path '*/.git/*' -printf '%T+ %p\\n' 2>/dev/null | sort | tail -25",
    ),
    (
        "nginx: кто стучится",
        "docker logs backend-nginx-1 --since 24h 2>&1 | tail -2000 | "
        "awk '{print $1}' | sort | uniq -c | sort -rn | head -10; "
        "echo '--- попытки в админку ---'; "
        "docker logs backend-nginx-1 --since 24h 2>&1 | grep -c 'auth/admin/login' || true",
    ),
    (
        "wdtt и WG (только чтение)",
        "systemctl is-active wdtt.service; "
        "sha256sum $(command -v wdtt-server 2>/dev/null || echo /usr/local/bin/wdtt-server) 2>/dev/null || true; "
        "wg show wdtt0 dump 2>/dev/null | wc -l",
    ),
]


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Read-only аудит Улья")
    p.add_argument("--attempts", type=int, default=CONNECT_ATTEMPTS,
                   help="сколько раз пробовать SSH (блок плавает)")
    p.add_argument("--pause", type=int, default=CONNECT_PAUSE_SEC,
                   help="пауза между попытками, сек")
    a = p.parse_args()

    client = connect_flaky(max(1, a.attempts), max(1, a.pause))
    try:
        for title, cmd in CHECKS:
            print(f"\n===== {title} =====")
            try:
                run(client, cmd, timeout=120)
            except Exception as e:  # аудит не должен падать из-за одного шага
                print(f"[skip] {title}: {type(e).__name__}: {e}")
    finally:
        client.close()
    print(
        "\nЧитать так: если в 'наш ли DROP на 443/22' есть DROP/REJECT или ufw deny — "
        "блок наш и снимается правкой правил. Если правил нет, а счётчик пакетов на 443 "
        "не растёт — пакеты не доходят, это внешний фильтр (ТСПУ/хостер)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
