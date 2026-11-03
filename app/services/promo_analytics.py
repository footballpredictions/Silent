"""Read-only acquisition, payment and return activity; promo quotas stay separate."""
from datetime import datetime, timedelta
from sqlalchemy import and_, case, func, select, union
from app.models import Device, Payment, Subscription, User

COUNT_KEYS = ('users_count', 'paid_users_count', 'subscribed_users_count', 'paid_active_users_count')


def _cohort():
    # pending_promo is cleared after payment. Historical payment/subscription
    # attribution keeps that user visible, without counting repeated invoices.
    sources = []
    for model, field in ((User, User.pending_promo_code), (Payment, Payment.promo_code), (Subscription, Subscription.promo_code)):
        uid = User.id if model is User else model.user_id
        sources.append(select(uid.label('user_id'), func.upper(func.trim(field)).label('code'))
            .where(field.is_not(None), func.trim(field) != ''))
    return union(*sources).subquery('promo_cohort')


def _rows(now):
    cohort = _cohort()
    received = func.coalesce(Payment.paid_amount, Payment.amount)
    paid_at = func.coalesce(Payment.completed_at, Payment.created_at)
    paid = select(Payment.user_id, func.count().label('paid_count'), func.sum(received).label('paid_total'),
        func.min(paid_at).label('first_paid_at'), func.max(paid_at).label('last_paid_at'))\
        .where(Payment.status == 'completed', received > 0).group_by(Payment.user_id).subquery('paid')
    subscriptions = select(Subscription.user_id, func.max(Subscription.expires_at).label('active_until'))\
        .where(Subscription.status == 'active', Subscription.expires_at > now)\
        .group_by(Subscription.user_id).subquery('live_subscription')
    paid_active = and_(paid.c.paid_count > 0, subscriptions.c.active_until.is_not(None),
        User.last_seen_at > paid.c.first_paid_at, User.last_seen_at >= now-timedelta(days=7),
        User.last_seen_at <= now+timedelta(minutes=5))
    return select(User.id.label('user_id'), User.email, User.created_at, User.last_seen_at, cohort.c.code,
        func.coalesce(paid.c.paid_count, 0).label('paid_count'), func.coalesce(paid.c.paid_total, 0).label('paid_total'),
        paid.c.first_paid_at, paid.c.last_paid_at, subscriptions.c.active_until,
        func.coalesce(paid_active, False).label('paid_active_7d'))\
        .select_from(cohort).join(User, User.id == cohort.c.user_id)\
        .outerjoin(paid, paid.c.user_id == User.id).outerjoin(subscriptions, subscriptions.c.user_id == User.id)


async def promo_campaigns(db, *, now=None):
    rows = _rows(now or datetime.utcnow()).subquery('promo_rows')
    query = select(rows.c.code, func.count().label('users_count'),
        func.sum(case((rows.c.paid_count > 0, 1), else_=0)).label('paid_users_count'),
        func.sum(case((rows.c.active_until.is_not(None), 1), else_=0)).label('subscribed_users_count'),
        func.sum(case((rows.c.paid_active_7d.is_(True), 1), else_=0)).label('paid_active_users_count'))\
        .group_by(rows.c.code).order_by(func.count().desc(), rows.c.code)
    return [dict(row) for row in (await db.execute(query)).mappings()]


def _iso(value):return value.isoformat(timespec='seconds')+'Z' if value else None


async def promo_totals(db, *, code=None, now=None):
    query = _rows(now or datetime.utcnow())
    if code and code.strip():query = query.where(query.selected_columns['code'] == code.strip().upper())
    attributed = query.subquery('attributed')
    users = select(attributed.c.user_id, attributed.c.paid_count, attributed.c.active_until,
        attributed.c.paid_active_7d).distinct().subquery('unique_promo_users')
    result = (await db.execute(select(func.count().label('users_count'),
        func.coalesce(func.sum(case((users.c.paid_count > 0, 1), else_=0)), 0).label('paid_users_count'),
        func.coalesce(func.sum(case((users.c.active_until.is_not(None), 1), else_=0)), 0).label('subscribed_users_count'),
        func.coalesce(func.sum(case((users.c.paid_active_7d.is_(True), 1), else_=0)), 0).label('paid_active_users_count'))
        .select_from(users))).mappings().one()
    return dict(result)


async def promo_users(db, *, code=None, activity='all', offset=0, limit=50, now=None):
    query = _rows(now or datetime.utcnow())
    if code and code.strip():query = query.where(query.selected_columns['code'] == code.strip().upper())
    if activity == 'paid':query = query.where(query.selected_columns['paid_count'] > 0)
    elif activity == 'unpaid':query = query.where(query.selected_columns['paid_count'] == 0)
    elif activity == 'paid_active':query = query.where(query.selected_columns['paid_active_7d'].is_(True))
    rows = query.subquery('promo_users')
    total = int(await db.scalar(select(func.count()).select_from(rows)) or 0)
    records = (await db.execute(select(rows).order_by(rows.c.created_at.desc(), rows.c.user_id, rows.c.code)
        .offset(offset).limit(limit))).mappings().all()
    ids = {row['user_id'] for row in records}
    devices = list((await db.scalars(select(Device).where(Device.user_id.in_(ids)))).all()) if ids else []
    from app.services.session_presence import session_online_flags
    online = await session_online_flags(devices) if devices else {}
    online_users = {device.user_id for device in devices if online.get(str(device.id))}
    items = []
    for row in records:
        uid = row['user_id']
        items.append({'user_id':str(uid), 'display_id':str(uid)[:8].upper(), 'email':row['email'], 'code':row['code'],
            'created_at':_iso(row['created_at']), 'last_seen_at':_iso(row['last_seen_at']),
            'has_paid':row['paid_count'] > 0, 'paid_count':row['paid_count'], 'paid_total':float(row['paid_total']),
            'first_paid_at':_iso(row['first_paid_at']), 'last_paid_at':_iso(row['last_paid_at']),
            'has_active_subscription':row['active_until'] is not None, 'active_until':_iso(row['active_until']),
            'paid_active_7d':bool(row['paid_active_7d']), 'vpn_online':uid in online_users})
    return {'items':items, 'total':total, 'offset':offset, 'limit':limit,
            'summary':await promo_totals(db, code=code, now=now)}
