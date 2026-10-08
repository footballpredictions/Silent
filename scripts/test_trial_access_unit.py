"""Trial dates follow first activation, and relogin/device changes cannot grant another trial."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models import Subscription
from app.services import subscription_service as service
from app.api import vpn as vpn_api
from app.api import auth as auth_api
from app.schemas.vpn import DeviceRegisterRequest
from starlette.requests import Request


class Rows:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return [] if self.value is None else [self.value]


class Db:
    def __init__(self, existing=None):
        self.execute = AsyncMock(return_value=Rows(existing))
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.added = []

    def add(self, value):
        self.added.append(value)


class TrialAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = SimpleNamespace(
            id=uuid4(), email="trial@example.test", is_admin=False,
            created_at=datetime(2026, 9, 17), is_verified=True,
        )

    async def test_delayed_verification_gets_three_days_from_activation(self):
        now = datetime(2026, 10, 8, 6, 28)
        clock = SimpleNamespace(utcnow=lambda: now)
        db = Db()
        with patch.object(service, "datetime", clock), \
             patch.object(service, "user_in_test_mode", AsyncMock(return_value=False)), \
             patch.object(service, "get_display_subscription", AsyncMock(return_value=None)):
            sub = await service.ensure_trial_subscription(db, self.user)
        self.assertEqual(sub.plan_type, "trial")
        self.assertEqual(sub.started_at, now)
        self.assertEqual(sub.expires_at, now + timedelta(days=3))
        self.assertGreater(sub.started_at, self.user.created_at)
        self.assertEqual(db.added, [sub])
        db.commit.assert_awaited_once()

    async def test_existing_active_trial_is_not_extended_by_login(self):
        expiry = datetime.utcnow() + timedelta(days=2)
        sub = Subscription(user_id=self.user.id, plan_type="trial", status="active", expires_at=expiry)
        db = Db()
        with patch.object(service, "user_in_test_mode", AsyncMock(return_value=False)), \
             patch.object(service, "get_display_subscription", AsyncMock(return_value=sub)):
            result = await service.ensure_trial_subscription(db, self.user)
        self.assertIs(result, sub)
        self.assertEqual(sub.expires_at, expiry)
        db.execute.assert_not_awaited()

    async def test_email_confirmation_starts_trial_today_despite_old_registration(self):
        now = datetime(2026, 10, 8, 6, 28)
        self.user.is_verified = False
        self.user.verification_token = "test-verification-token"
        db = Db()

        async def query_result(query):
            if query.column_descriptions[0].get("entity") is not Subscription:
                return Rows(self.user)
            return Rows()

        db.execute.side_effect = query_result
        with patch.object(service, "datetime", SimpleNamespace(utcnow=lambda: now)), \
             patch.object(service, "user_in_test_mode", AsyncMock(return_value=False)), \
             patch.object(service, "get_display_subscription", AsyncMock(return_value=None)), \
             patch("app.services.vk_agent_auth.is_agent_enabled", AsyncMock(return_value=False)):
            response = await auth_api.verify_email("test-verification-token", db=db)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.user.is_verified)
        self.assertIsNone(self.user.verification_token)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].started_at, now)
        self.assertEqual(db.added[0].expires_at, now + timedelta(days=3))

    async def test_other_accounts_on_same_phone_cannot_deny_this_accounts_live_trial(self):
        sub = Subscription(user_id=self.user.id, plan_type="trial", status="active",
                           expires_at=datetime.utcnow() + timedelta(days=3))
        device = SimpleNamespace(id=uuid4(), user_id=self.user.id,
                                 device_fingerprint="and-shared-phone", is_active=True)
        db = Db()
        other_user = uuid4()

        async def query_result(query):
            # The old cross-account trial join finds another account on this phone.
            if query.column_descriptions[0]["name"] == "user_id":
                return Rows(other_user)
            if query.column_descriptions[0].get("entity") is Subscription:
                return Rows()
            return Rows(device)

        db.execute.side_effect = query_result
        request = Request({"type": "http", "headers": []})
        expected = {"subscription_active": True}
        with patch.object(service, "user_in_test_mode", AsyncMock(return_value=False)), \
             patch.object(service, "get_display_subscription", AsyncMock(return_value=sub)), \
             patch("app.services.user_hash_service.ensure_user_server_hashes", AsyncMock()), \
             patch.object(vpn_api, "clear_stale_online_status", AsyncMock()), \
             patch.object(vpn_api, "register_device", AsyncMock()), \
             patch.object(vpn_api, "build_vpn_config_for_user", AsyncMock(return_value=expected)) as build:
            config = await vpn_api.get_config(device.device_fingerprint, request,
                                               user=self.user, db=db)
            self.assertEqual(config, expected)
            self.assertTrue(build.call_args.args[3])
            registration = await vpn_api.device_register(
                DeviceRegisterRequest(device_name="test phone", device_type="android",
                                      device_fingerprint=device.device_fingerprint),
                request, user=self.user, db=db,
            )
            self.assertEqual(registration, expected)
            self.assertTrue(build.call_args.args[3])
        self.assertEqual(sub.expires_at.date(), (datetime.utcnow() + timedelta(days=3)).date())
        db.commit.assert_not_awaited()

    async def test_expired_or_revoked_history_does_not_grant_a_new_trial(self):
        for historical_status in ("expired", "cancelled"):
            with self.subTest(status=historical_status):
                db = Db(existing=uuid4())
                with patch.object(service, "user_in_test_mode", AsyncMock(return_value=False)), \
                     patch.object(service, "get_display_subscription", AsyncMock(return_value=None)):
                    sub = await service.ensure_trial_subscription(db, self.user)
                    with self.assertRaises(vpn_api.HTTPException) as denied:
                        await service.require_active_subscription(self.user, db)
                    self.assertEqual(denied.exception.status_code, 402)
                self.assertIsNone(sub)
                self.assertEqual(db.added, [])
                db.commit.assert_not_awaited()

    async def test_admin_does_not_get_an_unnecessary_trial(self):
        self.user.is_admin = True
        db = Db()
        self.assertIsNone(await service.ensure_trial_subscription(db, self.user))
        db.execute.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
