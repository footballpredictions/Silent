"""Real SQL/HTTP promo attribution: registration survives consumption at payment."""
import sys,unittest,uuid
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import AsyncMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import test_prepaid_checkout_unit as checkout
from app.api.admin import router as admin_router
from app.core.deps import get_admin_credentials
from app.models import User,PromoCode,Payment,Subscription


class PromoAnalyticsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await checkout.CheckoutTests.asyncSetUp(self)
        self.app.include_router(admin_router,prefix='/api')
        self.app.dependency_overrides[get_admin_credentials]=lambda:True
        self.now=datetime.utcnow()
        self.promo=PromoCode(code='ЧЕЧИЛ',max_uses=10000,use_count=1)
        self.db.add(self.promo)
        self.pending=[]
        for n in range(10):
            user=User(email=f'pending{n}@example.org',password_hash='fixture',pending_promo_code='ЧЕЧИЛ',
                created_at=self.now-timedelta(days=20),last_seen_at=self.now-timedelta(days=19))
            self.db.add(user);self.pending.append(user)
        self.user.created_at=self.now-timedelta(days=30)
        self.user.last_seen_at=self.now-timedelta(days=1)
        self.user.pending_promo_code=None
        self.db.add(Payment(user_id=self.user.id,plan_type='monthly',amount=199,paid_amount=199,wallet='fixture',
            yumoney_label='paid-chechil',status='completed',promo_code='ЧЕЧИЛ',completed_at=self.now-timedelta(days=10)))
        self.db.add(Subscription(user_id=self.user.id,plan_type='monthly',status='active',amount_paid=199,
            started_at=self.now-timedelta(days=10),expires_at=self.now+timedelta(days=20),promo_code='ЧЕЧИЛ'))
        await self.db.commit()

    async def asyncTearDown(self):await checkout.CheckoutTests.asyncTearDown(self)

    async def test_list_distinguishes_eleven_users_from_one_quota_payment(self):
        response=await self.client.get('/api/admin/promo')
        self.assertEqual(response.status_code,200,response.text)
        promo=next(p for p in response.json() if p['code']=='ЧЕЧИЛ')
        self.assertEqual(promo['use_count'],1)
        self.assertEqual(promo['max_uses'],10000)
        self.assertEqual(promo.get('users_count'),11)
        self.assertEqual(promo.get('paid_users_count'),1)

    async def test_paid_user_does_not_disappear_when_pending_code_cleared(self):
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'code':'ЧЕЧИЛ'})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json();self.assertEqual(data['total'],11)
        paid=next(u for u in data['items'] if u['user_id']==str(self.user.id))
        self.assertTrue(paid['has_paid']);self.assertEqual(paid['paid_total'],199)
        self.assertTrue(paid['has_active_subscription']);self.assertTrue(paid['paid_active_7d'])
        unpaid=next(u for u in data['items'] if u['user_id']==str(self.pending[0].id))
        self.assertFalse(unpaid['has_paid']);self.assertFalse(unpaid['paid_active_7d'])

    async def test_campaign_summary_uses_unique_users_and_keeps_old_stats(self):
        self.db.add(Payment(user_id=self.user.id,plan_type='monthly',amount=199,wallet='fixture',
            yumoney_label='duplicate-pending',status='pending',promo_code='ЧЕЧИЛ'))
        await self.db.commit()
        response=await self.client.get('/api/admin/bonuses/stats')
        self.assertEqual(response.status_code,200,response.text)
        data=response.json();self.assertEqual(data['summary']['users_with_pending_promo'],10)
        campaign=next(p for p in data.get('promo_campaigns',[]) if p['code']=='ЧЕЧИЛ')
        self.assertEqual(campaign['users_count'],11);self.assertEqual(campaign['paid_users_count'],1)
        self.assertEqual(campaign['paid_active_users_count'],1)

    async def test_payment_without_return_is_not_counted_as_continued_usage(self):
        self.user.last_seen_at=self.now-timedelta(days=11)
        await self.db.commit()
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'code':'ЧЕЧИЛ'})
        self.assertEqual(response.status_code,200,response.text)
        paid=next(u for u in response.json()['items'] if u['user_id']==str(self.user.id))
        self.assertTrue(paid['has_paid']);self.assertFalse(paid['paid_active_7d'])

    async def test_pending_invoice_and_free_grant_are_not_paid_conversion(self):
        user=self.pending[0]
        self.db.add(Payment(user_id=user.id,plan_type='monthly',amount=199,wallet='fixture',
            yumoney_label='unpaid-invoice',status='pending',promo_code='ЧЕЧИЛ'))
        self.db.add(Subscription(user_id=user.id,plan_type='trial',status='active',amount_paid=0,
            expires_at=self.now+timedelta(days=1)))
        await self.db.commit()
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'code':'ЧЕЧИЛ'})
        self.assertEqual(response.status_code,200,response.text)
        entry=next(u for u in response.json()['items'] if u['user_id']==str(user.id))
        self.assertFalse(entry['has_paid']);self.assertTrue(entry['has_active_subscription'])
        self.assertFalse(entry['paid_active_7d'])

    async def test_paging_filter_and_admin_auth(self):
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'code':'ЧЕЧИЛ','limit':3,'offset':9})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['total'],11);self.assertEqual(len(response.json()['items']),2)
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'code':'UNKNOWN'})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['total'],0)
        from fastapi import HTTPException
        async def denied():raise HTTPException(401,'fixture')
        self.app.dependency_overrides[get_admin_credentials]=denied
        self.assertEqual((await self.client.get('/api/admin/bonuses/promo-users')).status_code,401)

    async def test_paid_active_filter_and_unique_global_summary(self):
        self.user.pending_promo_code='OTHER'
        await self.db.commit()
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'code':' чечил ','activity':'paid_active'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['total'],1)
        self.assertEqual(response.json()['items'][0]['user_id'],str(self.user.id))
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'code':'ЧЕЧИЛ','activity':'unpaid'})
        self.assertEqual(response.json()['total'],10)
        response=await self.client.get('/api/admin/bonuses/stats')
        self.assertEqual(response.json()['promo_summary']['users_count'],11)
        self.assertEqual(response.json()['promo_summary']['paid_users_count'],1)

    async def test_expired_sub_and_old_activity_do_not_count_as_retained(self):
        from sqlalchemy import update
        self.user.last_seen_at=self.now-timedelta(days=8)
        await self.db.commit()
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'activity':'paid_active'})
        self.assertEqual(response.json()['total'],0)
        self.user.last_seen_at=self.now-timedelta(hours=1)
        await self.db.execute(update(Subscription).where(Subscription.user_id==self.user.id).values(expires_at=self.now-timedelta(days=1)))
        await self.db.commit()
        response=await self.client.get('/api/admin/bonuses/promo-users',params={'activity':'paid_active'})
        self.assertEqual(response.json()['total'],0)


if __name__=='__main__':unittest.main()
