"""Unit tests: ссылки писем при заблокированном 443 Улья (без сети и БД)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.email_links import (  # noqa: E402
    email_action_links,
    is_public_email_base,
)

HIVE = "https://132-243-234-162.nip.io"
CELLS = ["http://87.58.213.193:9100", "http://78.17.74.27:9100"]


def test_verify_link_uses_cell_first_when_hive_443_blocked():
    """Кнопка = сота :9100 (как bootstrap). Улей в конце — 443 с РФ часто мёртв."""
    links = email_action_links("api/auth/verify-email", "tok1", HIVE, CELLS)
    assert links[0] == f"{CELLS[0]}/api/auth/verify-email?token=tok1"
    assert links[1] == f"{CELLS[1]}/api/auth/verify-email?token=tok1"
    assert links[-1] == f"{HIVE}/api/auth/verify-email?token=tok1"


def test_blocked_hive_has_cell_fallback_links():
    """2026-09-16: 443 Улья режут из РФ — в письме должна быть живая ссылка на соту."""
    links = email_action_links("api/auth/verify-email", "tok1", HIVE, CELLS)
    assert any(":9100/api/auth/verify-email?token=tok1" in u for u in links)
    assert len(links) == 3


def test_tunnel_and_localhost_bases_are_not_emailed():
    """Почту читают вне VPN: 10.66.66.1 в письме — мёртвая ссылка."""
    links = email_action_links(
        "api/auth/reset-password-page",
        "tok2",
        HIVE,
        ["http://10.66.66.1:8000", "http://localhost:8000", CELLS[0]],
    )
    assert not any("10.66.66.1" in u or "localhost" in u for u in links)
    assert links == [
        f"{CELLS[0]}/api/auth/reset-password-page?token=tok2",
        f"{HIVE}/api/auth/reset-password-page?token=tok2",
    ]


def test_hive_alt_ports_do_not_eat_fallback_slots():
    """Регресс 2026-09-16: `HIVE_API_ALT_PORTS` подмешал 4 мёртвых адреса Улья
    в начало `standby_api_urls`, и оба слота резерва уходили на ту же машину —
    ссылок на соты в письме не оставалось вовсе.
    """
    alt = [
        "https://132-243-234-162.nip.io:2083",
        "https://132.243.234.162:2083",
        "https://132-243-234-162.nip.io:2053",
        "https://132.243.234.162:2053",
    ]
    links = email_action_links(
        "api/auth/verify-email",
        "tok",
        HIVE,
        alt + CELLS,
        exclude_hosts=("132-243-234-162.nip.io", "132.243.234.162"),
    )
    assert links == [
        f"{CELLS[0]}/api/auth/verify-email?token=tok",
        f"{CELLS[1]}/api/auth/verify-email?token=tok",
        f"{HIVE}/api/auth/verify-email?token=tok",
    ], links


def test_one_fallback_per_machine():
    """Две ссылки на один хост умрут вместе — второй слот тратить на него нельзя."""
    links = email_action_links(
        "api/auth/verify-email",
        "tok",
        HIVE,
        [f"{CELLS[0]}", "http://87.58.213.193:9101", CELLS[1]],
    )
    assert links[0].startswith(CELLS[0])
    assert links[1].startswith(CELLS[1])
    assert links[-1].startswith(HIVE)


def test_primary_host_is_never_reused_as_fallback():
    links = email_action_links(
        "api/auth/verify-email", "tok", HIVE, [f"{HIVE}:2083", CELLS[0]]
    )
    assert len(links) == 2
    assert links[0].startswith(CELLS[0])
    assert links[1].startswith(HIVE)


def test_fallbacks_are_capped_and_deduped():
    links = email_action_links(
        "api/auth/verify-email",
        "tok3",
        HIVE,
        [CELLS[0], CELLS[0], CELLS[1], "http://192.177.26.38:9100"],
    )
    assert len(links) == 3, links
    assert len(set(links)) == len(links)


def test_no_token_no_links():
    assert email_action_links("api/auth/verify-email", "", HIVE, CELLS) == []


def test_public_base_check():
    assert is_public_email_base(HIVE)
    assert is_public_email_base(CELLS[0])
    assert not is_public_email_base("http://10.66.66.1:8000")
    assert not is_public_email_base("ftp://1.2.3.4")
    assert not is_public_email_base("")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"ok ({len(tests)} tests)")
