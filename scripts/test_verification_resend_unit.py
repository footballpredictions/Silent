"""Exercise verification retries without sending email or connecting to production."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from starlette.requests import Request

from app.api import auth
from app.schemas.auth import LoginRequest
from app.services import email_service


class VerificationResendTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user = SimpleNamespace(password_hash="test", is_active=True, is_verified=False,
                                    verification_token="first-link")
        self.db = SimpleNamespace(
            execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=self.user))),
            commit=AsyncMock(),
        )
        self.request = Request({"type": "http", "headers": []})
        self.body = LoginRequest(email="test@icloud.com", password="test-password")
        self.send = Mock(return_value=True)
        self.limit = AsyncMock(return_value=False)
        self.password = Mock(return_value=True)
        self.enterContext(patch.multiple(
            auth, send_verification_email=self.send, verify_password=self.password,
            check_ip_rate_limit=AsyncMock(return_value=False), is_rate_limited=self.limit,
            _email_fallback_bases=AsyncMock(return_value=[]), _email_smtp_relays=AsyncMock(return_value=[]),
        ))

    async def resend(self):
        return await auth.resend_verification(self.body, self.request, self.db)

    async def test_acceptance_reuses_original_link(self):
        self.assertEqual(await self.resend(), {"status": "accepted"})
        self.assertEqual(self.send.call_args.args[:2], ("test@icloud.com", "first-link"))
        self.db.commit.assert_awaited_once()

    async def test_mail_failure_returns_503(self):
        self.send.return_value = False
        with self.assertRaises(HTTPException) as error:
            await self.resend()
        self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(self.user.verification_token, "first-link")

    async def test_no_mail_for_verified_bad_password_or_limited(self):
        self.user.is_verified = True
        self.assertEqual(await self.resend(), {"status": "verified"})
        self.user.is_verified = False
        self.password.return_value = False
        with self.assertRaises(HTTPException) as error:
            await self.resend()
        self.assertEqual(error.exception.status_code, 401)
        self.password.return_value = True
        self.limit.return_value = True
        with self.assertRaises(HTTPException) as error:
            await self.resend()
        self.assertEqual(error.exception.status_code, 429)
        self.send.assert_not_called()

    def test_plain_and_html_have_the_same_confirmation_link(self):
        with patch.object(email_service, "_send", return_value=True) as send:
            email_service.send_verification_email("test@icloud.com", "test-token", "https://example.com", [], [])
        url = "https://example.com/api/auth/verify-email?token=test-token"
        self.assertIn(url, send.call_args.args[2])
        self.assertIn(url, send.call_args.kwargs["plain_body"])


if __name__ == "__main__":
    unittest.main()
