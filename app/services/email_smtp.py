"""SMTP с коротким таймаутом и только IPv4.

smtp.mail.ru отдаёт AAAA. В Docker IPv6 часто без маршрута: SYN висит, пока
ядро не вернёт ENETUNREACH (~минуты). smtplib.SMTP_SSL без timeout это и ловит.
"""
from __future__ import annotations

import smtplib
import socket
import ssl

SMTP_TIMEOUT_SEC = 12


def _tcp_ipv4(host: str, port: int, timeout: float) -> socket.socket:
    last: OSError | None = None
    infos = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"smtp: нет IPv4 для {host}")
    for fam, socktype, proto, _canon, sa in infos:
        sock = socket.socket(fam, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sa)
            return sock
        except OSError as e:
            last = e
            try:
                sock.close()
            except Exception:
                pass
    raise last or OSError(f"smtp: IPv4 {host}:{port} недоступен")


def handshake_smtp(smtp, sock, host: str, timeout: float) -> None:
    """Свой TCP+TLS: сначала 220, потом EHLO. Иначе AUTH «не поддерживается».

    SMTP_SSL() без connect не читает баннер. Следующий EHLO съедает 220,
    esmtp_features пустой → SMTPNotSupportedError. Прод: сота 502, письма нет.
    """
    smtp.timeout = timeout
    smtp.sock = sock
    smtp.file = None
    smtp._host = host
    code, msg = smtp.getreply()
    if int(code) != 220:
        raise smtplib.SMTPConnectError(code, msg)
    smtp.ehlo_or_helo_if_needed()


def open_smtp(host: str, port: int, *, timeout: float = SMTP_TIMEOUT_SEC):
    """Контекст не нужен: вызывающий делает quit/close. TLS на hostname, TCP на A."""
    host = (host or "").strip()
    port = int(port)
    timeout = float(timeout)
    raw = _tcp_ipv4(host, port, timeout)
    if port == 465:
        ctx = ssl.create_default_context()
        ssock = ctx.wrap_socket(raw, server_hostname=host)
        smtp = smtplib.SMTP_SSL()
        handshake_smtp(smtp, ssock, host, timeout)
        return smtp
    smtp = smtplib.SMTP()
    handshake_smtp(smtp, raw, host, timeout)
    smtp.starttls()
    smtp.ehlo()
    return smtp
