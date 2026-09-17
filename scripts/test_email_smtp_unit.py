"""SMTP с Улья: таймаут + IPv4, иначе очередь писем висит минутами.

Прод 2026-09-16/17: smtp.mail.ru:465, `[Errno 101] Network is unreachable`
через ~2–4 мин (SMTP_SSL без timeout). Пока висит BackgroundTasks,
следующие подтверждения тоже не уходят.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "unit-test-secret-key-not-for-prod")

from app.services.email_smtp import SMTP_TIMEOUT_SEC, open_smtp  # noqa: E402
from app.services.email_service import _send  # noqa: E402
from app.services.email_envelope import envelope_from, prefer_cells_first  # noqa: E402
from app.services.email_relays import smtp_relay_candidate_urls  # noqa: E402


def test_envelope_from_uses_smtp_user_when_domains_differ():
    """Gmail дропает From silent-vpn.ru через smtp.mail.ru."""
    assert (
        envelope_from("noreply@mail.ru", "noreply@silent-vpn.ru")
        == "noreply@mail.ru"
    )
    assert envelope_from("a@mail.ru", "a@mail.ru") == "a@mail.ru"
    assert envelope_from("a@mail.ru", "") == "a@mail.ru"


def test_prefer_cells_when_relays_exist():
    assert prefer_cells_first([{"api_url": "http://x:9100", "secret": "abcdefgh"}])
    assert not prefer_cells_first([])
    assert not prefer_cells_first(None)


def test_smtp_relay_urls_match_bootstrap_public_9100():
    """Улей шлёт smtp-send на тот же :9100, куда клиент ходит за API."""
    got = smtp_relay_candidate_urls(
        "http://87.58.213.193:9100",
        "http://10.66.66.1:8000",
        "http://87.58.213.193:9100",
    )
    assert got == ["http://87.58.213.193:9100"]


def test_smtp_timeout_is_short_enough_not_to_jam_register():
    """Ядро инцидента: 465 без timeout ждал SYN минутами."""
    assert 3 <= SMTP_TIMEOUT_SEC <= 15


def test_open_smtp_resolves_ipv4_only():
    seen: list[int] = []

    def fake_gai(host, port, family=0, type=0, proto=0, flags=0):
        seen.append(family)
        raise socket.gaierror("blocked")

    with patch("app.services.email_smtp.socket.getaddrinfo", fake_gai):
        try:
            open_smtp("smtp.mail.ru", 465, timeout=2)
        except OSError:
            pass
    assert seen == [socket.AF_INET], seen


class _FakeSmtpFile:
    def __init__(self):
        self._lines = [b"220 smtp.mail.ru ESMTP\r\n"]

    def readline(self, _limit=-1):
        if not self._lines:
            return b""
        return self._lines.pop(0)

    def close(self):
        return None


class _FakeSmtpSock:
    def __init__(self):
        self.file = _FakeSmtpFile()

    def makefile(self, _mode, _bufsize=None):
        return self.file

    def sendall(self, data):
        text = data.decode("ascii", "replace").lower()
        if text.startswith("ehlo"):
            self.file._lines.extend(
                [
                    b"250-smtp.mail.ru\r\n",
                    b"250-AUTH PLAIN LOGIN\r\n",
                    b"250 OK\r\n",
                ]
            )
        elif text.startswith("helo"):
            self.file._lines.append(b"250 smtp.mail.ru\r\n")
        elif text.startswith("quit"):
            self.file._lines.append(b"221 bye\r\n")

    def close(self):
        return None


def test_open_smtp_465_reads_220_banner_before_ehlo():
    """Прод 2026-09-17: сота 502 SMTPNotSupportedError — EHLO съел баннер 220, AUTH нет."""
    fake = _FakeSmtpSock()

    class _Ctx:
        def wrap_socket(self, _sock, server_hostname=None):
            return fake

    with (
        patch("app.services.email_smtp._tcp_ipv4", return_value=object()),
        patch("app.services.email_smtp.ssl.create_default_context", return_value=_Ctx()),
    ):
        smtp = open_smtp("smtp.mail.ru", 465, timeout=2)
    assert smtp.has_extn("auth"), smtp.esmtp_features
    smtp.close()


def test_send_relays_via_cell_first_without_waiting_hive():
    """Улей 12с ENETUNREACH не должен стоять перед живой сотой."""
    posts: list[dict] = []

    class Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            posts.append(
                {
                    "url": url,
                    "secret": (headers or {}).get("X-Cell-Agent-Secret"),
                    "to": (json or {}).get("to"),
                    "mail_from": (json or {}).get("mail_from"),
                }
            )
            return Resp()

    with (
        patch("app.services.email_service.open_smtp", side_effect=AssertionError("hive smtp must wait")),
        patch("app.services.email_service.httpx.Client", Client),
        patch("app.services.email_service.settings") as s,
    ):
        s.SMTP_USER = "noreply@mail.ru"
        s.SMTP_PASS = "p"
        s.EMAIL_FROM = "noreply@silent-vpn.ru"
        s.EMAIL_FROM_NAME = "Silent VPN"
        s.SMTP_HOST = "smtp.mail.ru"
        s.SMTP_PORT = 465
        ok = _send(
            "new.user@gmail.com",
            "Silent VPN — подтвердите email",
            "<p>hi</p>",
            smtp_relays=[
                {"api_url": "http://87.58.213.193:9100", "secret": "cell-secret"}
            ],
        )
    assert ok is True
    assert posts and posts[0]["url"].endswith("/v1/smtp-send")
    assert posts[0]["secret"] == "cell-secret"
    assert posts[0]["to"] == "new.user@gmail.com"
    assert posts[0]["mail_from"] == "noreply@mail.ru"


def test_send_hive_when_no_relays():
    class FakeSmtp:
        def login(self, *a):
            return None

        def sendmail(self, *a):
            return None

        def quit(self):
            return None

        def close(self):
            return None

    with (
        patch("app.services.email_service.open_smtp", return_value=FakeSmtp()),
        patch("app.services.email_service.settings") as s,
    ):
        s.SMTP_USER = "noreply@mail.ru"
        s.SMTP_PASS = "p"
        s.EMAIL_FROM = "noreply@silent-vpn.ru"
        s.EMAIL_FROM_NAME = "Silent VPN"
        s.SMTP_HOST = "smtp.mail.ru"
        s.SMTP_PORT = 465
        ok = _send("a@b.c", "subj", "<p>x</p>", smtp_relays=[])
    assert ok is True


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ok ({len(tests)} tests)")
