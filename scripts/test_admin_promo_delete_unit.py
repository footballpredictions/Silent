"""Promo deletion through real SQL/HTTP; no production payments or VPN calls."""
import sys
import unittest
import uuid
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from scripts import test_prepaid_checkout_unit as checkout
from app.api.admin import router as admin_router
from app.core.deps import get_admin_credentials
from app.models import PromoCode, Payment, Subscription
from app.services.payment_service import PLAN_PRICES


class PromoDeleteTests(unittest.IsolatedAsyncioTestCase):
    notification = checkout.CheckoutTests.notification

    async def asyncSetUp(self):
        await checkout.CheckoutTests.asyncSetUp(self)
        self.app.include_router(admin_router, prefix='/api')
        self.app.dependency_overrides[get_admin_credentials] = lambda: True
        self.promo = PromoCode(code='DELETE20', discount_percent=20, extra_days=3, max_uses=20,
                               expires_at=datetime(2027, 1, 1))
        self.other = PromoCode(code='KEEP10', discount_percent=10, max_uses=10, is_active=False)
        self.db.add_all([self.promo,self.other]);await self.db.commit()
        self.url = '/api/admin/promo/'+str(self.promo.id)

    async def asyncTearDown(self):
        await checkout.CheckoutTests.asyncTearDown(self)

    async def test_delete_hides_only_selected_code_and_preserves_history(self):
        self.promo.use_count=2
        self.user.pending_promo_code=self.promo.code
        payment=Payment(user_id=self.user.id,plan_type='monthly',amount=159.2,wallet='test-wallet',
                        yumoney_label='historic-promo',promo_code=self.promo.code,status='completed')
        self.db.add(payment);await self.db.commit()
        subs_before=list((await self.db.execute(select(Subscription.id))).scalars())
        response=await self.client.delete(self.url)
        self.assertEqual(response.status_code,200,response.text)
        listed=(await self.client.get('/api/admin/promo')).json()
        self.assertEqual([p['id'] for p in listed],[str(self.other.id)])
        self.assertIsNotNone(await self.db.get(PromoCode,self.promo.id))
        self.assertFalse(self.promo.is_active)
        self.assertEqual(self.promo.use_count,2)
        self.assertEqual(self.user.pending_promo_code,self.promo.code)
        self.assertEqual((await self.db.get(Payment,payment.id)).promo_code,self.promo.code)
        self.assertEqual(list((await self.db.execute(select(Subscription.id))).scalars()),subs_before)

    async def test_removed_code_cannot_be_applied_or_discount_a_new_invoice(self):
        await self.client.delete(self.url)
        response=await self.client.post('/api/payments/promo/check',json={'code':self.promo.code,'plan_type':'monthly'})
        self.assertEqual(response.status_code,404,response.text)
        self.user.pending_promo_code=self.promo.code;await self.db.commit()
        response=await self.client.post('/api/payments/preview',json={'plan_type':'monthly'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertIsNone(response.json()['promo_code'])
        self.assertEqual(response.json()['amount'],PLAN_PRICES['monthly'][0])

    async def test_existing_discounted_payment_can_still_complete(self):
        response=await self.client.post('/api/payments/init',json={'plan_type':'monthly','promo_code':self.promo.code})
        self.assertEqual(response.status_code,200,response.text)
        invoice=response.json()
        self.assertEqual((await self.client.delete(self.url)).status_code,200)
        notification=self.notification(invoice['label'],str(invoice['amount']))
        response=await self.client.post('/api/payments/yumoney/notify',data=notification)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['reason'],'completed')
        payment=await self.db.scalar(select(Payment).where(Payment.yumoney_label==invoice['label']))
        self.assertTrue(payment.subscription_applied)
        self.assertEqual(payment.promo_code,self.promo.code)
        self.assertEqual(self.promo.use_count,1)

    async def test_repeated_delete_is_idempotent(self):
        self.assertEqual((await self.client.delete(self.url)).status_code,200)
        self.assertEqual((await self.client.delete(self.url)).status_code,200)
        self.assertEqual((await self.client.get('/api/admin/promo')).json()[0]['code'],self.other.code)

    async def test_unknown_or_invalid_id_is_rejected(self):
        self.assertEqual((await self.client.delete('/api/admin/promo/'+str(uuid.uuid4()))).status_code,404)
        self.assertEqual((await self.client.delete('/api/admin/promo/not-a-uuid')).status_code,422)
        self.assertTrue(self.promo.is_active)

    async def test_requires_admin_credentials(self):
        self.app.dependency_overrides.pop(get_admin_credentials)
        self.assertEqual((await self.client.delete(self.url)).status_code,401)
        self.assertTrue(self.promo.is_active)


if __name__=='__main__':unittest.main()
