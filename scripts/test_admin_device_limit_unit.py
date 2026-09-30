"""Regression: a manual 3/5 device limit changes effective client and VPN limit only."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import subscription_service as service  # noqa: E402
from app.api import admin as admin_api  # noqa: E402
from app.services import test_mode_settings  # noqa: E402


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeDb:
    def __init__(self, user, subscription):
        self.user = user
        self.subscription = subscription
        self.calls = 0
        self.commits = 0

    async def execute(self, query):
        self.calls += 1
        if self.calls == 1:
            return Rows([self.user])
        if self.calls == 5:
            return Rows([self.subscription])
        return Rows([])

    async def commit(self):
        self.commits += 1


async def test_effective_limit_uses_manual_choice_without_changing_plan():
    async def no_test_mode(user, db):
        return False

    async def active_subscription(db, user, *, in_test_mode):
        return SimpleNamespace(plan_type=user.plan_type)

    original_test_mode = service.user_in_test_mode
    original_subscription = service.get_display_subscription
    service.user_in_test_mode = no_test_mode
    service.get_display_subscription = active_subscription
    try:
        user = SimpleNamespace(
            email="customer@example.test", is_admin=False,
            plan_type="monthly_5", device_limit_override=3,
        )
        assert await service.max_devices_for_user(None, user) == 3
        assert user.plan_type == "monthly_5"
        user.plan_type = "monthly"
        user.device_limit_override = 5
        assert await service.max_devices_for_user(None, user) == 5
        user.device_limit_override = None
        assert await service.max_devices_for_user(None, user) == 3
        user.plan_type = "monthly_5"
        assert await service.max_devices_for_user(None, user) == 5
        user.is_admin = True
        assert await service.max_devices_for_user(None, user) == 0
    finally:
        service.user_in_test_mode = original_test_mode
        service.get_display_subscription = original_subscription


async def test_admin_list_and_update_keep_paid_plan():
    async def no_global_test(db):
        return False

    async def no_test_mode(user, db):
        return False

    async def active_subscription(db, user, *, in_test_mode):
        return sub

    original_global = test_mode_settings.is_registration_test_mode_enabled
    original_test_mode = service.user_in_test_mode
    original_subscription = service.get_display_subscription
    test_mode_settings.is_registration_test_mode_enabled = no_global_test
    service.user_in_test_mode = no_test_mode
    service.get_display_subscription = active_subscription
    try:
        uid = uuid4()
        user = SimpleNamespace(
            id=uid, display_id=str(uid)[:8].upper(), email="customer@example.test",
            is_admin=False, is_verified=True, is_active=True,
            is_test_user=False, test_mode_personal=False, test_mode_excluded=False,
            created_at=None, bootstrap_hash=None, referral_code=None,
            referred_by_user_id=None, pending_promo_code=None,
            device_limit_override=None,
        )
        sub = SimpleNamespace(
            user_id=uid, status="active", is_active=True, plan_type="monthly_5",
            expires_at="2026-11-01T00:00:00Z",
        )
        db = FakeDb(user, sub)
        listed = await admin_api.list_users(skip=0, limit=None, _=True, db=db)
        assert listed[0]["max_devices"] == 5
        assert listed[0]["plan_max_devices"] == 5
        assert listed[0]["device_limit_override"] is None

        db = FakeDb(user, sub)
        updated = await admin_api.set_user_device_limit(
            user_id=uid, req=admin_api.UserDeviceLimitRequest(max_devices=3), _=True, db=db,
        )
        assert db.commits == 1
        assert updated == {"max_devices": 3, "device_limit_override": 3}
        assert sub.plan_type == "monthly_5"
        assert sub.expires_at == "2026-11-01T00:00:00Z"

        db = FakeDb(user, sub)
        listed = await admin_api.list_users(skip=0, limit=None, _=True, db=db)
        assert listed[0]["max_devices"] == 3
        assert listed[0]["plan_max_devices"] == 5
        assert listed[0]["device_limit_override"] == 3

        db = FakeDb(user, sub)
        reset = await admin_api.set_user_device_limit(
            user_id=uid, req=admin_api.UserDeviceLimitRequest(max_devices=None), _=True, db=db,
        )
        assert reset == {"max_devices": 5, "device_limit_override": None}
        assert sub.plan_type == "monthly_5"
        try:
            admin_api.UserDeviceLimitRequest(max_devices=4)
        except ValidationError:
            pass
        else:
            raise AssertionError("Only 3, 5, or plan default may be selected")

        user.is_admin = True
        db = FakeDb(user, sub)
        try:
            await admin_api.set_user_device_limit(
                user_id=uid, req=admin_api.UserDeviceLimitRequest(max_devices=5), _=True, db=db,
            )
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Admin users must remain unlimited")
        assert db.commits == 0
    finally:
        test_mode_settings.is_registration_test_mode_enabled = original_global
        service.user_in_test_mode = original_test_mode
        service.get_display_subscription = original_subscription


if __name__ == "__main__":
    asyncio.run(test_effective_limit_uses_manual_choice_without_changing_plan())
    asyncio.run(test_admin_list_and_update_keep_paid_plan())
    print("ok: manual override, admin API, paid-plan fallback")
