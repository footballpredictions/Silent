"""Standalone unit tests for referral helpers (no FastAPI install required)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import importlib.util
from pathlib import Path


def _load_normalize_only():
    """Те же правила, что referral_service, без импорта FastAPI."""
    from urllib.parse import parse_qs, urlparse

    def _code_from_link(text: str):
        parsed = urlparse(text)
        qs = parse_qs(parsed.query)
        host = (parsed.hostname or "").lower()
        if parsed.scheme.lower() == "silentvpn" and host == "ref":
            values = qs.get("code") or []
        else:
            values = qs.get("ref") or qs.get("code") or []
        if not values:
            return None
        return values[0].strip() or None

    def normalize_code(raw):
        if raw is None:
            return None
        text = raw.strip()
        if not text:
            return None
        if "://" in text:
            extracted = _code_from_link(text)
            if extracted:
                text = extracted
        code = text.strip().upper()
        return code or None

    def build_referral_link(code: str) -> str:
        return f"https://silentvpn3.github.io/?ref={code}"

    return normalize_code, build_referral_link


class ReferralPureHelpersTests(unittest.TestCase):
    def test_normalize_and_link(self):
        normalize_code, build_referral_link = _load_normalize_only()
        self.assertEqual(normalize_code("  ab12  "), "AB12")
        self.assertIsNone(normalize_code(""))
        self.assertIsNone(normalize_code(None))
        self.assertEqual(normalize_code("silentvpn://ref?code=abcd1234"), "ABCD1234")
        self.assertEqual(normalize_code("https://silentvpn3.github.io/?ref=abcd1234"), "ABCD1234")
        self.assertEqual(
            build_referral_link("ABCD1234"),
            "https://silentvpn3.github.io/?ref=ABCD1234",
        )


class ReferralRewardMockTests(unittest.IsolatedAsyncioTestCase):
    async def test_apply_reward_skips_when_not_first_payment(self):
        # Import only if fastapi available; else skip with container test
        try:
            from app.services.referral_service import apply_referral_reward_after_payment
        except ModuleNotFoundError:
            self.skipTest("fastapi not installed locally; covered by remote_referral_db_test")

        db = AsyncMock()
        payment = SimpleNamespace(user_id="invitee-1", id="pay-1")
        reward = SimpleNamespace(
            invitee_id="invitee-1",
            inviter_id="inviter-1",
            status="pending",
            payment_id=None,
            rewarded_at=None,
        )
        reward_result = MagicMock()
        reward_result.scalar_one_or_none.return_value = reward
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        db.execute = AsyncMock(side_effect=[reward_result, count_result])

        ok = await apply_referral_reward_after_payment(db, payment)
        self.assertFalse(ok)
        self.assertEqual(reward.status, "pending")

    async def test_apply_reward_on_first_payment(self):
        try:
            from app.services.referral_service import apply_referral_reward_after_payment
        except ModuleNotFoundError:
            self.skipTest("fastapi not installed locally; covered by remote_referral_db_test")

        db = AsyncMock()
        db.commit = AsyncMock()
        payment = SimpleNamespace(user_id="invitee-1", id="pay-1")
        reward = SimpleNamespace(
            invitee_id="invitee-1",
            inviter_id="inviter-1",
            status="pending",
            payment_id=None,
            rewarded_at=None,
        )
        reward_result = MagicMock()
        reward_result.scalar_one_or_none.return_value = reward
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        db.execute = AsyncMock(side_effect=[reward_result, count_result])

        with patch(
            "app.services.referral_service.extend_subscription_days",
            new_callable=AsyncMock,
        ) as extend:
            ok = await apply_referral_reward_after_payment(db, payment)

        self.assertTrue(ok)
        self.assertEqual(reward.status, "rewarded")
        self.assertEqual(reward.payment_id, "pay-1")
        self.assertEqual(extend.await_count, 2)
        db.commit.assert_awaited()


if __name__ == "__main__":
    unittest.main(verbosity=2)
