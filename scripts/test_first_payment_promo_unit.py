"""Real SQL/HTTP promo checks; no external money, mail or VPN operations."""
import unittest
from datetime import datetime, timedelta
from sqlalchemy import delete, select

from scripts import test_prepaid_checkout_unit as checkout_fixture
from app.models import Payment, PromoCode, Subscription, User
from app.services.payment_service import PLAN_PRICES
from app.services.referral_service import bind_referral_on_register, find_valid_promo


class FirstPaymentPromoTests(unittest.IsolatedAsyncioTestCase):
    notification = checkout_fixture.CheckoutTests.notification

    async def asyncSetUp(self):
        await checkout_fixture.CheckoutTests.asyncSetUp(self)
        await self.db.execute(delete(Subscription))
        self.promo = PromoCode(code='ЧЕЧИЛ', discount_percent=30, max_uses=10000,
                               first_payment_only=True, expires_at=datetime(2027, 10, 24))
        self.db.add(self.promo)
        await self.db.commit()

    async def asyncTearDown(self):
        await checkout_fixture.CheckoutTests.asyncTearDown(self)

    async def test_registration_code_applies_to_all_seven_tariffs(self):
        promo = await find_valid_promo(self.db, 'ЧЕЧИЛ')
        await bind_referral_on_register(self.db, self.user, None, promo)
        await self.db.commit()
        for plan, (price, _) in PLAN_PRICES.items():
            with self.subTest(plan=plan):
                response = await self.client.post('/api/payments/preview', json={'plan_type': plan})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['amount'], round(price * .7, 2))
                self.assertEqual(response.json()['promo_code'], 'ЧЕЧИЛ')
        self.assertEqual(self.promo.use_count, 0)

    async def test_existing_unpaid_user_check_binds_code_for_checkout(self):
        checked = await self.client.post('/api/payments/promo/check', json={'code': '  чечил  ', 'plan_type': 'monthly'})
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.json()['discounted_price'], round(PLAN_PRICES['monthly'][0] * .7, 2))
        self.assertEqual(self.user.pending_promo_code, 'ЧЕЧИЛ')
        response = await self.client.post('/api/payments/init', json={'plan_type': 'monthly'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['amount'], checked.json()['discounted_price'])
        repeat = await self.client.post('/api/payments/init', json={'plan_type': 'monthly'})
        self.assertEqual(repeat.json()['label'], response.json()['label'])
        different = await self.client.post('/api/payments/init', json={'plan_type': 'quarterly'})
        self.assertEqual(different.status_code, 400)
        self.assertEqual(self.promo.use_count, 0)

    async def test_registration_profile_quotes_show_discount_before_first_payment(self):
        from app.services.payment_service import profile_payment_previews
        self.user.pending_promo_code = self.promo.code
        await self.db.commit()
        previews = await profile_payment_previews(self.db, self.user)
        self.assertEqual(len(previews), 6)
        for plan, quote in previews.items():
            self.assertEqual(quote['amount'], round(PLAN_PRICES[plan][0] * .7, 2))
            self.assertEqual(quote['promo_code'], self.promo.code)
        self.assertEqual(self.promo.use_count, 0)

    async def test_legacy_promo_remains_available_for_returning_customer(self):
        self.promo.first_payment_only = False
        self.db.add(Payment(user_id=self.user.id, plan_type='monthly', amount=199, wallet='test-wallet',
                            yumoney_label='silent_legacy_customer', status='completed'))
        await self.db.commit()
        response = await self.client.post('/api/payments/promo/check', json={'code': 'ЧЕЧИЛ', 'plan_type': 'monthly'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.user.pending_promo_code, 'ЧЕЧИЛ')
        quote = await self.client.post('/api/payments/preview', json={'plan_type': 'monthly_5'})
        self.assertEqual(quote.json()['amount'], round(PLAN_PRICES['monthly_5'][0] * .7, 2))

    async def test_invalid_code_does_not_replace_previously_applied_promo(self):
        self.user.pending_promo_code = 'ЧЕЧИЛ'
        await self.db.commit()
        response = await self.client.post('/api/payments/promo/check', json={'code': 'missing-code', 'plan_type': 'monthly'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.user.pending_promo_code, 'ЧЕЧИЛ')

    async def test_success_consumes_once_and_blocks_second_discount(self):
        response = await self.client.post('/api/payments/init', json={'plan_type': 'monthly', 'promo_code': 'ЧЕЧИЛ'})
        self.assertEqual(response.status_code, 200)
        invoice = response.json()
        notice = self.notification(invoice['label'], str(invoice['amount']))
        paid = await self.client.post('/api/payments/yumoney/notify', data=notice)
        self.assertEqual(paid.status_code, 200)
        self.assertEqual(self.promo.use_count, 1)
        await self.client.post('/api/payments/yumoney/notify', data=notice)
        self.assertEqual(self.promo.use_count, 1)
        checked = await self.client.post('/api/payments/promo/check', json={'code': 'ЧЕЧИЛ', 'plan_type': 'yearly'})
        self.assertEqual(checked.status_code, 400)
        preview = await self.client.post('/api/payments/preview', json={'plan_type': 'monthly', 'promo_code': 'ЧЕЧИЛ'})
        self.assertEqual(preview.json()['amount'], PLAN_PRICES['monthly'][0])
        self.assertIsNone(preview.json()['promo_code'])

    async def test_completed_payment_without_subscription_also_blocks_code(self):
        self.db.add(Payment(user_id=self.user.id, plan_type='monthly', amount=199, wallet='test-wallet',
                            yumoney_label='silent_old_payment', status='completed'))
        await self.db.commit()
        response = await self.client.post('/api/payments/promo/check', json={'code': 'ЧЕЧИЛ', 'plan_type': 'monthly'})
        self.assertEqual(response.status_code, 400)

    async def test_expired_inactive_exhausted_and_unknown_plan_are_rejected(self):
        for field, value in [('expires_at', datetime(2020, 1, 1)), ('is_active', False), ('use_count', 10000)]:
            original = getattr(self.promo, field)
            setattr(self.promo, field, value)
            await self.db.commit()
            response = await self.client.post('/api/payments/promo/check', json={'code': 'ЧЕЧИЛ', 'plan_type': 'monthly'})
            self.assertGreaterEqual(response.status_code, 400)
            setattr(self.promo, field, original)
        await self.db.commit()
        response = await self.client.post('/api/payments/promo/check', json={'code': 'ЧЕЧИЛ', 'plan_type': 'missing'})
        self.assertEqual(response.status_code, 400)

    async def test_reservations_cannot_exceed_campaign_limit(self):
        self.promo.use_count = 9999
        other = User(email='other@example.org', password_hash='local-test', is_verified=True)
        self.db.add(other)
        await self.db.flush()
        self.db.add(Payment(user_id=other.id, plan_type='monthly', amount=139.3, wallet='test-wallet',
                            yumoney_label='silent_other_user', promo_code='ЧЕЧИЛ', status='pending'))
        await self.db.commit()
        response = await self.client.post('/api/payments/init', json={'promo_code': 'ЧЕЧИЛ', 'plan_type': 'monthly'})
        self.assertEqual(response.status_code, 400)

    async def test_reserved_first_invoice_remains_payable_without_new_discount_invoice(self):
        response = await self.client.post('/api/payments/init', json={'plan_type': 'monthly', 'promo_code': 'ЧЕЧИЛ'})
        self.assertEqual(response.status_code, 200)
        payment = (await self.db.execute(select(Payment).where(Payment.yumoney_label == response.json()['label']))).scalar_one()
        payment.created_at = datetime(2020, 1, 1)
        await self.db.commit()
        status = await self.client.get('/api/payments/status/' + payment.yumoney_label)
        self.assertEqual(status.json()['status'], 'pending')
        self.assertEqual(self.promo.use_count, 0)


if __name__ == '__main__':
    unittest.main()
