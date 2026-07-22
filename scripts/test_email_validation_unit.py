"""Unit tests: registration email anti-abuse (no DB)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.email_validation import (  # noqa: E402
    BLOCKED_EMAIL_DOMAINS,
    canonical_email,
    classify_email_suspicion,
    validate_registration_email_domain,
)


def test_block_internet_ru_anonymizer():
    err = validate_registration_email_domain("anon123@internet.ru")
    assert err
    low = err.lower()
    assert "аноним" in low or "однораз" in low or "запрещ" in low


def test_block_plus_alias():
    err = validate_registration_email_domain("name+trial2@gmail.com")
    assert err and "+" in err


def test_block_apple_hide_my_email():
    err = validate_registration_email_domain("x@privaterelay.appleid.com")
    assert err


def test_allow_mail_ru_main():
    assert validate_registration_email_domain("user.name@mail.ru") is None


def test_allow_gmail():
    assert validate_registration_email_domain("user.name@gmail.com") is None


def test_canonical_gmail_dots():
    assert canonical_email("a.b.c@gmail.com") == canonical_email("abc@gmail.com")
    assert canonical_email("abc@googlemail.com") == canonical_email("abc@gmail.com")


def test_internet_ru_not_in_whitelist_config():
    from app.config import settings

    allowed = {d.lower() for d in settings.ALLOWED_EMAIL_DOMAINS}
    assert "internet.ru" not in allowed
    assert "internet.ru" in BLOCKED_EMAIL_DOMAINS


def test_block_dotted_gmail_alias():
    assert validate_registration_email_domain("x.ha.rp.erd.e.a.n@gmail.com")
    assert validate_registration_email_domain("siets.ie.tn.oac.h@gmail.com")


def test_block_mailru_random_anonymizer():
    assert validate_registration_email_domain("504c52c1f5lc@mail.ru")
    assert validate_registration_email_domain("trmq1h2hekdm@mail.ru")
    assert validate_registration_email_domain("8vjzcomtkhzu@mail.ru")


def test_allow_normal_mailru():
    assert validate_registration_email_domain("chameleon31@mail.ru") is None
    assert validate_registration_email_domain("vova.voloshin83@mail.ru") is None
    assert validate_registration_email_domain("pixik96@mail.ru") is None


def test_classify_report_helpers():
    assert classify_email_suspicion("benirop916@suahi.com") == "disposable_domain"
    assert classify_email_suspicion("na5me@internet.ru") == "anonymizer_domain"
    assert classify_email_suspicion("504c52c1f5lc@mail.ru") == "mailru_anonymizer_local"
    assert classify_email_suspicion("x.ha.rp.erd.e.a.n@gmail.com") == "dotted_alias"
    assert classify_email_suspicion("reynsia7+5crp1@gmail.com") == "plus_alias"
    assert classify_email_suspicion("igor.bykov.3006@gmail.com") is None


def main():
    tests = [
        test_block_internet_ru_anonymizer,
        test_block_plus_alias,
        test_block_apple_hide_my_email,
        test_allow_mail_ru_main,
        test_allow_gmail,
        test_canonical_gmail_dots,
        test_internet_ru_not_in_whitelist_config,
        test_block_dotted_gmail_alias,
        test_block_mailru_random_anonymizer,
        test_allow_normal_mailru,
        test_classify_report_helpers,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"OK  {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} OK")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
