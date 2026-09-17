"""Unit tests: skip email confirmation (admin Extra Settings). No DB."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.email_confirmation_policy import (  # noqa: E402
    login_allows_unverified,
    register_payload,
    register_verification_plan,
    setting_is_on,
    skip_confirmation,
    strip_runtime_theme_keys,
)


def test_default_off_missing_or_garbage():
    assert setting_is_on(None) is False
    assert setting_is_on("") is False
    assert setting_is_on("false") is False
    assert setting_is_on("no") is False
    assert setting_is_on("maybe") is False


def test_on_truthy_strings():
    assert setting_is_on("true")
    assert setting_is_on("TRUE")
    assert setting_is_on("1")
    assert setting_is_on(" yes ")
    assert setting_is_on("on")


def test_register_default_needs_email():
    verified, send_mail = register_verification_plan(skip=False)
    assert verified is False
    assert send_mail is True
    body = register_payload(skip=False)
    assert body["email_confirmation_required"] == "true"
    assert "подтвержд" in body["message"].lower() or "проверьте email" in body["message"].lower()


def test_register_skip_auto_verifies_and_no_mail():
    verified, send_mail = register_verification_plan(skip=True)
    assert verified is True
    assert send_mail is False
    body = register_payload(skip=True)
    assert body["email_confirmation_required"] == "false"
    assert "войти" in body["message"].lower()


def test_login_blocks_unverified_when_confirmation_on():
    assert login_allows_unverified(skip=False, is_verified=False) is False
    assert login_allows_unverified(skip=False, is_verified=True) is True


def test_login_allows_unverified_when_skip_on():
    assert login_allows_unverified(skip=True, is_verified=False) is True
    assert login_allows_unverified(skip=True, is_verified=True) is True


def test_client_skip_from_theme_or_register_flag():
    assert skip_confirmation(theme_skip=False, required_flag=None) is False
    assert skip_confirmation(theme_skip=True, required_flag=None) is True
    assert skip_confirmation(theme_skip=False, required_flag="true") is False
    assert skip_confirmation(theme_skip=False, required_flag="false") is True
    assert skip_confirmation(theme_skip=False, required_flag=False) is True
    # Старый клиент без поля + тумблер выкл — экран «проверьте email»
    assert skip_confirmation(theme_skip=False, required_flag="") is False


def test_theme_store_does_not_keep_skip_flag():
    dumped = strip_runtime_theme_keys(
        {"app_name": "Silent VPN", "skip_email_confirmation": True}
    )
    assert dumped == {"app_name": "Silent VPN"}
    assert "skip_email_confirmation" not in dumped


def main():
    tests = [
        test_default_off_missing_or_garbage,
        test_on_truthy_strings,
        test_register_default_needs_email,
        test_register_skip_auto_verifies_and_no_mail,
        test_login_blocks_unverified_when_confirmation_on,
        test_login_allows_unverified_when_skip_on,
        test_client_skip_from_theme_or_register_flag,
        test_theme_store_does_not_keep_skip_flag,
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
