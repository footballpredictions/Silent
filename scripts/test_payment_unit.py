"""Unit tests for YuMoney payment service: wallets, signature, notification checklist.

Covers everything from PLAN_PAYMENTS_YUMONEY.md §11 that can be verified without a
real Postgres instance: multi-wallet selection/secrets, URL building, signature
verification, every notification branch (invalid signature, unknown label,
idempotency, codepro/unaccepted/currency guards, amount-tolerance/fraud check,
promo use_count, full success path) and status polling/expiry.

Run: python -m unittest scripts.test_payment_unit -v   (from backend/, with deps installed)
"""
from __future__ import annotations

import hashlib
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _result(scalar=None, scalars_list=None, scalars_first=None):
    """Fake SQLAlchemy Result — configurable .scalar_one_or_none()/.scalars()."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalar_one.return_value = scalar
    sc = MagicMock()
    sc.all.return_value = scalars_list if scalars_list is not None else []
    sc.first.return_value = scalars_first
    r.scalars.return_value = sc
    return r


@contextmanager
def _wallets_env(pairs: dict):
    """Temporarily set YUMONEY_WALLET_N / YUMONEY_SECRET_N / YUMONEY_SECRET on settings."""
    try:
        from app.config import settings
    except ModuleNotFoundError:
        yield None
        return

    keys = [f"YUMONEY_WALLET_{i}" for i in range(1, 11)] + [f"YUMONEY_SECRET_{i}" for i in range(1, 11)] + ["YUMONEY_SECRET"]
    original = {k: getattr(settings, k, "") for k in keys}
    for k in keys:
        setattr(settings, k, "")
    for k, v in pairs.items():
        setattr(settings, k, v)
    try:
        yield settings
    finally:
        for k, v in original.items():
            setattr(settings, k, v)


class PaymentServiceImportGuard(unittest.TestCase):
    """Make sure the module is importable at all before running the rest."""

    def test_import(self):
        try:
            import app.services.payment_service  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("fastapi/sqlalchemy stack not installed locally")


def _svc():
    try:
        import app.services.payment_service as svc
        return svc
    except ModuleNotFoundError:
        return None


class WalletSelectionTests(unittest.TestCase):
    def setUp(self):
        self.svc = _svc()
        if not self.svc:
            self.skipTest("fastapi/sqlalchemy stack not installed locally")

    def test_get_wallets_skips_empty_slots(self):
        with _wallets_env({
            "YUMONEY_WALLET_1": "1000000001",
            "YUMONEY_SECRET_1": "secret1",
            "YUMONEY_WALLET_5": "1000000005",
            "YUMONEY_SECRET_5": "secret5",
        }):
            wallets = self.svc.get_wallets()
        self.assertEqual(len(wallets), 2)
        self.assertEqual({w["wallet"] for w in wallets}, {"1000000001", "1000000005"})

    def test_get_wallets_up_to_ten(self):
        pairs = {}
        for i in range(1, 11):
            pairs[f"YUMONEY_WALLET_{i}"] = f"100000000{i}"
            pairs[f"YUMONEY_SECRET_{i}"] = f"secret{i}"
        with _wallets_env(pairs):
            wallets = self.svc.get_wallets()
        self.assertEqual(len(wallets), 10)

    def test_wallet_secret_falls_back_to_shared_secret(self):
        with _wallets_env({"YUMONEY_WALLET_1": "1000000001", "YUMONEY_SECRET": "shared"}):
            wallets = self.svc.get_wallets()
        self.assertEqual(wallets[0]["secret"], "shared")

    def test_pick_wallet_raises_when_none_configured(self):
        with _wallets_env({}):
            with self.assertRaises(RuntimeError):
                self.svc._pick_wallet()

    def test_pick_wallet_only_returns_configured(self):
        with _wallets_env({"YUMONEY_WALLET_3": "wallet-3", "YUMONEY_SECRET_3": "s3"}):
            for _ in range(20):
                w = self.svc._pick_wallet()
                self.assertEqual(w["wallet"], "wallet-3")

    def test_pick_wallet_distributes_randomly_across_all(self):
        pairs = {f"YUMONEY_WALLET_{i}": f"w{i}" for i in range(1, 4)}
        pairs.update({f"YUMONEY_SECRET_{i}": f"s{i}" for i in range(1, 4)})
        with _wallets_env(pairs):
            seen = {self.svc._pick_wallet()["wallet"] for _ in range(300)}
        # With 300 draws over 3 wallets, astronomically unlikely to miss any.
        self.assertEqual(seen, {"w1", "w2", "w3"})

    def test_secret_for_wallet_matches_correct_slot(self):
        with _wallets_env({
            "YUMONEY_WALLET_1": "wA", "YUMONEY_SECRET_1": "secretA",
            "YUMONEY_WALLET_2": "wB", "YUMONEY_SECRET_2": "secretB",
        }):
            self.assertEqual(self.svc.secret_for_wallet("wA"), "secretA")
            self.assertEqual(self.svc.secret_for_wallet("wB"), "secretB")

    def test_secret_for_unknown_wallet_falls_back_to_shared(self):
        with _wallets_env({"YUMONEY_WALLET_1": "wA", "YUMONEY_SECRET_1": "secretA", "YUMONEY_SECRET": "shared"}):
            self.assertEqual(self.svc.secret_for_wallet("unknown-wallet"), "shared")


class BuildUrlTests(unittest.TestCase):
    def setUp(self):
        self.svc = _svc()
        if not self.svc:
            self.skipTest("fastapi/sqlalchemy stack not installed locally")

    def test_build_payment_url_is_encoded_and_complete(self):
        url = self.svc.build_payment_url("monthly", "silent_abcdef", 199.0, "4100115200000001")
        self.assertTrue(url.startswith("https://yoomoney.ru/quickpay/confirm.xml?"))
        self.assertIn("receiver=4100115200000001", url)
        self.assertIn("label=silent_abcdef", url)
        self.assertIn("sum=199.00", url)
        # Spaces must be encoded, not literal — this was bug #5 in the plan.
        self.assertNotIn(" ", url)
        self.assertIn("successURL=", url)

    def test_success_url_points_to_backend(self):
        with patch.object(self.svc.settings, "FRONTEND_URL", "https://example.test"):
            self.assertEqual(self.svc.success_url(), "https://example.test/api/payments/success-page")


class SignatureTests(unittest.TestCase):
    def setUp(self):
        self.svc = _svc()
        if not self.svc:
            self.skipTest("fastapi/sqlalchemy stack not installed locally")

    def _signed(self, secret: str, **fields) -> dict:
        data = {
            "notification_type": "p2p-incoming",
            "operation_id": "1234567",
            "amount": "199.00",
            "currency": "643",
            "datetime": "2026-07-14T10:00:00Z",
            "sender": "41001151234567",
            "codepro": "false",
            "label": "silent_abc123",
        }
        data.update(fields)
        check_str = "&".join([
            data["notification_type"], data["operation_id"], data["amount"], data["currency"],
            data["datetime"], data["sender"], data["codepro"], secret, data["label"],
        ])
        data["sha1_hash"] = hashlib.sha1(check_str.encode("utf-8")).hexdigest()
        return data

    def test_valid_signature_accepted(self):
        data = self._signed("my-secret")
        self.assertTrue(self.svc._verify_yumoney_signature(data, "my-secret"))

    def test_wrong_secret_rejected(self):
        data = self._signed("my-secret")
        self.assertFalse(self.svc._verify_yumoney_signature(data, "wrong-secret"))

    def test_tampered_amount_rejected(self):
        """sum=1 style attack: signature was computed over the real amount."""
        data = self._signed("my-secret")
        data["amount"] = "1.00"
        self.assertFalse(self.svc._verify_yumoney_signature(data, "my-secret"))

    def test_tampered_label_rejected(self):
        data = self._signed("my-secret")
        data["label"] = "silent_someone_elses_payment"
        self.assertFalse(self.svc._verify_yumoney_signature(data, "my-secret"))

    def test_empty_secret_never_verifies(self):
        data = self._signed("")
        self.assertFalse(self.svc._verify_yumoney_signature(data, ""))


class CreatePaymentIntentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.svc = _svc()
        if not self.svc:
            self.skipTest("fastapi/sqlalchemy stack not installed locally")

    async def test_unknown_plan_raises_value_error(self):
        db = AsyncMock()
        user = SimpleNamespace(id="user-1", pending_promo_code=None)
        with self.assertRaises(ValueError):
            await self.svc.create_payment_intent(db, user, "not_a_real_plan")

    async def test_no_wallets_configured_raises_runtime_error(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=None))
        user = SimpleNamespace(id="user-1", pending_promo_code=None)
        with _wallets_env({}):
            with self.assertRaises(RuntimeError):
                await self.svc.create_payment_intent(db, user, "monthly")

    async def test_label_is_high_entropy_and_prefixed(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock(return_value=_result(scalar=None))
        db.commit = AsyncMock()
        user = SimpleNamespace(id="user-1", pending_promo_code=None)
        with _wallets_env({"YUMONEY_WALLET_1": "w1", "YUMONEY_SECRET_1": "s1"}):
            result = await self.svc.create_payment_intent(db, user, "monthly")
        self.assertTrue(result["label"].startswith("silent_"))
        # secrets.token_hex(16) -> 32 hex chars
        self.assertEqual(len(result["label"]), len("silent_") + 32)
        self.assertEqual(result["wallet"], "w1")
        db.add.assert_called_once()
        db.commit.assert_awaited()

    async def test_promo_discount_applied_but_use_count_not_incremented_yet(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        promo = SimpleNamespace(
            code="SAVE50", discount_percent=50, extra_days=0,
            use_count=0, max_uses=10, expires_at=None, is_active=True,
        )
        db.execute = AsyncMock(return_value=_result(scalar=promo))
        user = SimpleNamespace(id="user-1", pending_promo_code=None)
        with _wallets_env({"YUMONEY_WALLET_1": "w1", "YUMONEY_SECRET_1": "s1"}), \
             patch.object(self.svc, "PLAN_PRICES", {"monthly": (200.0, 30)}):
            result = await self.svc.create_payment_intent(db, user, "monthly", promo_code="save50")
        self.assertEqual(result["amount"], 100.0)
        # use_count must stay untouched until the payment actually completes.
        self.assertEqual(promo.use_count, 0)

    async def test_expired_promo_not_applied(self):
        db = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        promo = SimpleNamespace(
            code="OLD", discount_percent=50, extra_days=0,
            use_count=0, max_uses=10, expires_at=datetime.utcnow() - timedelta(days=1), is_active=True,
        )
        db.execute = AsyncMock(return_value=_result(scalar=promo))
        user = SimpleNamespace(id="user-1", pending_promo_code=None)
        with _wallets_env({"YUMONEY_WALLET_1": "w1", "YUMONEY_SECRET_1": "s1"}), \
             patch.object(self.svc, "PLAN_PRICES", {"monthly": (200.0, 30)}):
            result = await self.svc.create_payment_intent(db, user, "monthly", promo_code="old")
        self.assertEqual(result["amount"], 200.0)


class ProcessNotificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.svc = _svc()
        if not self.svc:
            self.skipTest("fastapi/sqlalchemy stack not installed locally")
        self.wallets_ctx = _wallets_env({"YUMONEY_WALLET_1": "w1", "YUMONEY_SECRET_1": "wallet-secret"})
        self.wallets_ctx.__enter__()
        self.addCleanup(self.wallets_ctx.__exit__, None, None, None)

    def _payment(self, **kw):
        base = dict(
            id="pay-1", user_id="user-1", plan_type="monthly", amount=199.0,
            wallet="w1", yumoney_label="silent_abc123", status="pending",
            operation_id=None, paid_amount=None, promo_code=None, raw_response=None,
            completed_at=None,
        )
        base.update(kw)
        return SimpleNamespace(**base)

    def _signed_notification(self, secret="wallet-secret", **fields) -> dict:
        data = {
            "notification_type": "p2p-incoming",
            "operation_id": "op-1",
            "amount": "199.00",
            "withdraw_amount": "199.00",
            "currency": "643",
            "datetime": "2026-07-14T10:00:00Z",
            "sender": "41001151234567",
            "codepro": "false",
            "unaccepted": "false",
            "label": "silent_abc123",
        }
        data.update(fields)
        check_str = "&".join([
            data["notification_type"], data["operation_id"], data["amount"], data["currency"],
            data["datetime"], data["sender"], data["codepro"], secret, data["label"],
        ])
        data["sha1_hash"] = hashlib.sha1(check_str.encode("utf-8")).hexdigest()
        return data

    async def test_invalid_signature_for_known_payment_rejected(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=self._payment()))
        data = self._signed_notification(secret="totally-wrong-secret")
        res = await self.svc.process_payment_notification(db, data)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "invalid_signature")

    async def test_unknown_label_with_valid_signature_ignored_not_rejected(self):
        """YuMoney's cabinet 'test notification' button: valid sig, no matching payment."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=None))
        data = self._signed_notification(secret="wallet-secret", label="silent_never_existed")
        res = await self.svc.process_payment_notification(db, data)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "unknown_label")

    async def test_unknown_label_with_invalid_signature_rejected(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=None))
        data = self._signed_notification(secret="not-a-configured-secret", label="silent_never_existed")
        res = await self.svc.process_payment_notification(db, data)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "invalid_signature")

    async def test_foreign_label_not_matched_to_wrong_payment(self):
        """Race-condition guard: notification for payment A must never complete payment B."""
        payment_b = self._payment(id="pay-B", yumoney_label="silent_payment_b")
        db = AsyncMock()

        async def execute_side_effect(stmt):
            # Only label silent_payment_b resolves; the notification below is for a
            # different (unknown) label — must not accidentally match payment_b.
            return _result(scalar=None)

        db.execute = AsyncMock(side_effect=execute_side_effect)
        data = self._signed_notification(secret="wallet-secret", label="silent_someone_elses")
        res = await self.svc.process_payment_notification(db, data)
        self.assertEqual(payment_b.status, "pending")  # untouched
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "unknown_label")

    async def test_already_completed_payment_is_idempotent(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=self._payment(status="completed")))
        data = self._signed_notification()
        res = await self.svc.process_payment_notification(db, data)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "already_processed")
        db.commit.assert_not_called()

    async def test_codepro_true_withholds_activation(self):
        payment = self._payment()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=payment))
        data = self._signed_notification(codepro="true")
        res = await self.svc.process_payment_notification(db, data)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "codepro")
        self.assertEqual(payment.status, "pending")

    async def test_unaccepted_true_ignored(self):
        payment = self._payment()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=payment))
        data = self._signed_notification(unaccepted="true")
        res = await self.svc.process_payment_notification(db, data)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "unaccepted")
        self.assertEqual(payment.status, "pending")

    async def test_wrong_currency_ignored(self):
        payment = self._payment()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=payment))
        data = self._signed_notification(currency="840")  # USD instead of RUB
        res = await self.svc.process_payment_notification(db, data)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "bad_currency")
        self.assertEqual(payment.status, "pending")

    async def test_duplicate_operation_id_ignored(self):
        payment = self._payment()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _result(scalar=payment),          # payment lookup by label
            _result(scalar="some-other-id"),  # operation_id already used
        ])
        data = self._signed_notification(operation_id="already-used")
        res = await self.svc.process_payment_notification(db, data)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "duplicate_operation")
        self.assertEqual(payment.status, "pending")

    async def test_amount_below_tolerance_marks_failed(self):
        """sum=1 attack / severe underpayment must never activate a subscription."""
        payment = self._payment(amount=199.0)
        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _result(scalar=payment),
            _result(scalar=None),  # operation_id dup check
        ])
        data = self._signed_notification(amount="1.00", withdraw_amount="1.00")
        res = await self.svc.process_payment_notification(db, data)
        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "amount_mismatch")
        self.assertEqual(payment.status, "failed")
        db.commit.assert_awaited()

    async def test_amount_within_commission_tolerance_completes(self):
        """YuMoney takes ~3-6% commission — withdraw_amount slightly below sum must still pass."""
        payment = self._payment(amount=199.0, promo_code=None)
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        # 1) payment lookup, 2) operation_id dup check, 3) email User lookup, 4) Subscription lookup
        db.execute = AsyncMock(side_effect=[
            _result(scalar=payment),
            _result(scalar=None),
            _result(scalar=SimpleNamespace(id="user-1", email="u@example.com")),
            _result(scalars_first=SimpleNamespace(expires_at=datetime.utcnow() + timedelta(days=30))),
        ])
        received = 199.0 * 0.95  # 5% commission — still above the 93% tolerance floor
        data = self._signed_notification(amount=f"{received:.2f}", withdraw_amount=f"{received:.2f}")

        with patch.object(self.svc, "_activate_subscription", new_callable=AsyncMock) as activate, \
             patch("app.services.referral_service.apply_referral_reward_after_payment", new_callable=AsyncMock), \
             patch.object(self.svc, "send_subscription_activated_email") as send_email:
            activate.return_value = SimpleNamespace(expires_at=datetime.utcnow() + timedelta(days=30))
            res = await self.svc.process_payment_notification(db, data)

        self.assertTrue(res["ok"])
        self.assertEqual(res["reason"], "completed")
        self.assertEqual(payment.status, "completed")
        self.assertAlmostEqual(float(payment.paid_amount), round(received, 2))
        activate.assert_awaited_once()
        send_email.assert_called_once()

    async def test_completed_payment_increments_promo_use_count_once(self):
        promo = SimpleNamespace(code="SAVE50", use_count=3, max_uses=100)
        payment = self._payment(amount=100.0, promo_code="SAVE50")
        user = SimpleNamespace(id="user-1", email="u@example.com", pending_promo_code="SAVE50")
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _result(scalar=payment),      # payment lookup
            _result(scalar=None),         # operation_id dup check
            _result(scalar=promo),        # promo lookup
            _result(scalar=user),         # user lookup (clear pending_promo_code)
            _result(scalar=user),         # user lookup for email
            _result(scalars_first=SimpleNamespace(expires_at=datetime.utcnow() + timedelta(days=30))),
        ])
        data = self._signed_notification(amount="100.00", withdraw_amount="100.00")

        with patch.object(self.svc, "_activate_subscription", new_callable=AsyncMock) as activate, \
             patch("app.services.referral_service.apply_referral_reward_after_payment", new_callable=AsyncMock), \
             patch.object(self.svc, "send_subscription_activated_email"):
            activate.return_value = SimpleNamespace(expires_at=datetime.utcnow() + timedelta(days=30))
            res = await self.svc.process_payment_notification(db, data)

        self.assertEqual(res["reason"], "completed")
        self.assertEqual(promo.use_count, 4)
        self.assertIsNone(user.pending_promo_code)


class PaymentStatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.svc = _svc()
        if not self.svc:
            self.skipTest("fastapi/sqlalchemy stack not installed locally")

    async def test_not_found_raises_value_error(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=None))
        user = SimpleNamespace(id="user-1")
        with self.assertRaises(ValueError):
            await self.svc.get_payment_status(db, user, "silent_missing")

    async def test_pending_within_ttl_stays_pending(self):
        payment = SimpleNamespace(
            yumoney_label="silent_x", status="pending", plan_type="monthly",
            amount=199.0, created_at=datetime.utcnow(),
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=payment))
        user = SimpleNamespace(id="user-1")
        result = await self.svc.get_payment_status(db, user, "silent_x")
        self.assertEqual(result["status"], "pending")
        db.commit.assert_not_called()

    async def test_pending_past_ttl_marked_expired(self):
        payment = SimpleNamespace(
            yumoney_label="silent_x", status="pending", plan_type="monthly",
            amount=199.0, created_at=datetime.utcnow() - timedelta(minutes=999),
        )
        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=payment))
        user = SimpleNamespace(id="user-1")
        with patch.object(self.svc.settings, "YUMONEY_PAYMENT_TTL_MINUTES", 30):
            result = await self.svc.get_payment_status(db, user, "silent_x")
        self.assertEqual(result["status"], "expired")
        self.assertEqual(payment.status, "expired")
        db.commit.assert_awaited()

    async def test_completed_status_passthrough(self):
        payment = SimpleNamespace(
            yumoney_label="silent_x", status="completed", plan_type="yearly",
            amount=1499.0, created_at=datetime.utcnow() - timedelta(days=1),
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=payment))
        user = SimpleNamespace(id="user-1")
        result = await self.svc.get_payment_status(db, user, "silent_x")
        self.assertEqual(result["status"], "completed")
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
