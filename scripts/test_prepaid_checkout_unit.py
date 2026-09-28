"""Checkout through HTTP, with a local in-memory SQL database and no live payments."""
import hashlib
import hmac
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import update

from app.api.payments import router
from app.core.deps import get_verified_user
from app.database import Base, get_db
from app.models import User, Subscription
from app.services.payment_service import settings


class CheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[
                Base.metadata.tables[name] for name in
                ("users", "subscriptions", "payments", "promo_codes", "referral_rewards", "devices", "app_settings")
            ]))
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.user = User(email="renewal@example.org", password_hash="local-test", is_verified=True)
        self.db.add(self.user)
        await self.db.flush()
        self.db.add(Subscription(user_id=self.user.id, plan_type="monthly", status="active",
                    amount_paid=199, started_at=datetime(2026, 9, 1), expires_at=datetime(2026, 10, 1)))
        await self.db.commit()
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")
        async def database():
            yield self.db
        self.app.dependency_overrides[get_db] = database
        self.app.dependency_overrides[get_verified_user] = lambda: self.user
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://local-test")
        self.patches = [
            patch.object(settings, "YUMONEY_WALLET_1", "test-wallet"),
            patch.object(settings, "YUMONEY_SECRET_1", "local-only-secret"),
            patch("app.services.payment_service.datetime"),
            patch("app.services.payment_service.send_subscription_activated_email"),
            # The OS process adapter is the only VPN mock: never run host docker/iptables.
            patch("subprocess.run", return_value=SimpleNamespace(stdout="true", stderr="", returncode=0)),
        ]
        for index, item in enumerate(self.patches):
            value = item.start()
            if index == 2:
                self.clock = value
                value.utcnow.return_value = datetime(2026, 9, 16)

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()

    def notification(self, label, amount="330.00"):
        data = dict(notification_type="p2p-incoming", operation_id="renewal-operation",
                    amount=amount, withdraw_amount=amount, currency="643",
                    datetime="2026-09-16T00:00:00Z", sender="local-test", codepro="false",
                    unaccepted="false", label=label)
        canonical = "&".join(f"{key}={quote(value, safe='')}" for key, value in sorted(data.items()))
        data["sign"] = hmac.new(b"local-only-secret", canonical.encode(), hashlib.sha256).hexdigest()
        return data

    async def test_preview_pending_settlement_and_replay(self):
        preview = await self.client.post("/api/payments/preview", json={"plan_type": "monthly_5"})
        self.assertEqual(preview.status_code, 200)
        expected = preview.json()
        self.assertEqual(expected["amount"], 330)
        self.assertEqual(expected["expires_at"], "2026-10-25T01:05:27Z")
        intent = (await self.client.post("/api/payments/init", json={"plan_type": "monthly_5"})).json()
        pending = (await self.client.get("/api/payments/status/" + intent["label"])).json()
        self.assertEqual(pending["status"], "pending")
        self.assertFalse(pending["subscription_applied"])
        data = self.notification(intent["label"])
        settled = await self.client.post("/api/payments/yumoney/notify", data=data)
        self.assertEqual(settled.json()["reason"], "completed")
        paid = (await self.client.get("/api/payments/status/" + intent["label"])).json()
        self.assertTrue(paid["subscription_applied"])
        self.assertEqual(paid["expires_at"], expected["expires_at"])
        self.assertEqual(paid["max_devices"], 5)
        replay = await self.client.post("/api/payments/yumoney/notify", data=data)
        self.assertEqual(replay.json()["reason"], "already_processed")
        self.assertEqual((await self.client.get("/api/payments/status/" + intent["label"])).json(), paid)

    async def test_profile_quotes_match_checkout_without_creating_a_payment(self):
        from app.services.payment_service import profile_payment_previews
        previews = await profile_payment_previews(self.db, self.user)
        self.assertEqual(len(previews), 6)
        expected = (await self.client.post("/api/payments/preview", json={"plan_type": "monthly_5"})).json()
        self.assertEqual(previews["monthly_5"]["message"], expected["message"])
        self.assertEqual(previews["monthly_5"]["expires_at"], expected["expires_at"])
        self.assertEqual(previews["monthly_5"]["calculated_at"], "2026-09-16T00:00:00Z")

    async def test_three_month_upgrade_preview_and_activation_add_both_terms(self):
        self.clock.utcnow.return_value = datetime(2026, 9, 28)
        await self.db.execute(update(Subscription).values(status="cancelled"))
        self.db.add(Subscription(user_id=self.user.id, plan_type="quarterly", status="active",
                    amount_paid=478, started_at=datetime(2026, 9, 28), expires_at=datetime(2026, 12, 28)))
        await self.db.commit()
        preview = (await self.client.post("/api/payments/preview", json={"plan_type": "quarterly_5"})).json()
        self.assertEqual(preview["purchased_days"], 91)
        self.assertEqual(preview["carried_days"], 55)
        self.assertEqual(preview["expires_at"], "2027-02-20T22:07:16Z")
        intent = (await self.client.post("/api/payments/init", json={"plan_type": "quarterly_5"})).json()
        self.assertEqual(intent["amount"], 792)
        data = self.notification(intent["label"], "792.00")
        settled = await self.client.post("/api/payments/yumoney/notify", data=data)
        self.assertEqual(settled.json()["reason"], "completed")
        paid = (await self.client.get("/api/payments/status/" + intent["label"])).json()
        self.assertEqual(paid["expires_at"], preview["expires_at"])
        self.assertEqual(paid["max_devices"], 5)


if __name__ == "__main__":
    unittest.main()
