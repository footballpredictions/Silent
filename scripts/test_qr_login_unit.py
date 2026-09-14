"""QR-вход: payload + сессия/код пользователя (без FastAPI)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.qr_login_service import (  # noqa: E402
    KIND_SESSION,
    KIND_USER,
    MemoryQrStore,
    QrLoginError,
    QrLoginService,
    build_qr_payload,
    parse_qr_payload,
)


class QrPayloadTests(unittest.TestCase):
    def test_roundtrip_session(self):
        uri = build_qr_payload(KIND_SESSION, "Abc_123-token")
        self.assertEqual(uri, "silentvpn://qr?k=s&c=Abc_123-token")
        parsed = parse_qr_payload(uri)
        self.assertEqual(parsed.kind, KIND_SESSION)
        self.assertEqual(parsed.code, "Abc_123-token")

    def test_roundtrip_user(self):
        uri = build_qr_payload(KIND_USER, "userCode99")
        parsed = parse_qr_payload(uri)
        self.assertEqual(parsed.kind, KIND_USER)
        self.assertEqual(parsed.code, "userCode99")

    def test_ignores_other_schemes(self):
        self.assertIsNone(parse_qr_payload("silentvpn://ref?code=ABCD"))
        self.assertIsNone(parse_qr_payload("https://example.com/qr?k=s&c=x"))
        https = parse_qr_payload("https://example.com/qr?k=s&c=Abc_123-token")
        self.assertIsNotNone(https)
        self.assertEqual(https.kind, KIND_SESSION)
        self.assertEqual(https.code, "Abc_123-token")
        self.assertIsNone(parse_qr_payload(""))
        self.assertIsNone(parse_qr_payload("silentvpn://qr?k=s&c="))
        self.assertIsNone(parse_qr_payload("silentvpn://qr?k=x&c=abc"))


class QrLoginServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = [1_000_000.0]
        self.store = MemoryQrStore(clock=lambda: self.now[0])
        self.svc = QrLoginService(
            self.store,
            session_ttl=120,
            user_code_ttl=120,
            clock=lambda: self.now[0],
        )

    def _advance(self, seconds: float) -> None:
        self.now[0] += seconds

    async def test_start_then_poll_pending(self):
        started = await self.svc.start_session()
        self.assertEqual(started.expires_in, 120)
        parsed = parse_qr_payload(started.payload)
        self.assertEqual(parsed.kind, KIND_SESSION)
        self.assertEqual(parsed.code, started.token)
        poll = await self.svc.poll_session(started.token)
        self.assertEqual(poll.status, "pending")
        self.assertIsNone(poll.user_id)

    async def test_phone_approves_tv_session_once(self):
        started = await self.svc.start_session()
        await self.svc.approve_session("user-1", started.token)
        poll = await self.svc.poll_session(started.token)
        self.assertEqual(poll.status, "approved")
        self.assertEqual(poll.user_id, "user-1")
        again = await self.svc.poll_session(started.token)
        self.assertEqual(again.status, "approved")
        self.assertEqual(again.user_id, "user-1")

    async def test_approve_unknown_or_used_fails(self):
        with self.assertRaises(QrLoginError) as ctx:
            await self.svc.approve_session("user-1", "no-such-token")
        self.assertIn(ctx.exception.code, ("not_found", "expired"))

        started = await self.svc.start_session()
        await self.svc.approve_session("user-1", started.token)
        with self.assertRaises(QrLoginError) as ctx2:
            await self.svc.approve_session("user-2", started.token)
        self.assertEqual(ctx2.exception.code, "already_used")

    async def test_session_expires(self):
        started = await self.svc.start_session()
        self._advance(121)
        poll = await self.svc.poll_session(started.token)
        self.assertEqual(poll.status, "expired")
        with self.assertRaises(QrLoginError) as ctx:
            await self.svc.approve_session("user-1", started.token)
        self.assertEqual(ctx.exception.code, "expired")

    async def test_user_code_redeems_once(self):
        issued = await self.svc.issue_user_code("user-7")
        self.assertEqual(issued.expires_in, 120)
        parsed = parse_qr_payload(issued.payload)
        self.assertEqual(parsed.kind, KIND_USER)
        self.assertEqual(parsed.code, issued.code)
        user_id = await self.svc.redeem_user_code(issued.code)
        self.assertEqual(user_id, "user-7")
        with self.assertRaises(QrLoginError) as ctx:
            await self.svc.redeem_user_code(issued.code)
        self.assertIn(ctx.exception.code, ("not_found", "expired", "already_used"))

    async def test_new_user_code_invalidates_previous(self):
        first = await self.svc.issue_user_code("user-7")
        second = await self.svc.issue_user_code("user-7")
        self.assertNotEqual(first.code, second.code)
        with self.assertRaises(QrLoginError):
            await self.svc.redeem_user_code(first.code)
        self.assertEqual(await self.svc.redeem_user_code(second.code), "user-7")

    async def test_approve_via_payload_uri(self):
        started = await self.svc.start_session()
        await self.svc.approve_payload("user-1", started.payload)
        poll = await self.svc.poll_session(started.token)
        self.assertEqual(poll.user_id, "user-1")

    async def test_redeem_via_payload_uri(self):
        issued = await self.svc.issue_user_code("user-3")
        self.assertEqual(await self.svc.redeem_payload(issued.payload), "user-3")

    async def test_wrong_kind_rejected(self):
        started = await self.svc.start_session()
        with self.assertRaises(QrLoginError):
            await self.svc.redeem_payload(started.payload)
        issued = await self.svc.issue_user_code("user-3")
        with self.assertRaises(QrLoginError):
            await self.svc.approve_payload("user-1", issued.payload)


def main() -> None:
    unittest.main()


if __name__ == "__main__":
    main()
