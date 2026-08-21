"""Admin helpers: support-code lookup, orphan payments, user subscription history."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select, func, or_, cast, String as SAString
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Payment, Subscription
from app.services.payment_service import normalize_support_code
from app.services.subscription_service import (
    get_display_subscription,
    grant_manual_subscription,
    user_in_test_mode,
    is_user_admin,
    TEST_PLAN,
)

logger = logging.getLogger(__name__)

BOOTSTRAP_EMAIL = "__bootstrap__@silent.local"


def _user_brief(user: User, *, admin: bool, in_test: bool, sub: Subscription | None) -> dict:
    return {
        "id": str(user.id),
        "display_id": user.display_id,
        "email": user.email,
        "is_verified": user.is_verified,
        "is_active": user.is_active,
        "is_admin": admin,
        "is_test_user": bool(getattr(user, "test_mode_personal", False)),
        "test_mode_excluded": bool(getattr(user, "test_mode_excluded", False)),
        "in_test_mode": in_test,
        "subscription": {
            "active": True if admin or in_test else (sub.is_active if sub else False),
            "plan": "unlimited" if admin else ("test" if in_test else (sub.plan_type if sub else None)),
            "expires_at": None if admin or in_test else (sub.expires_at if sub else None),
            "started_at": None if admin or in_test else (sub.started_at if sub else None),
        },
    }


def _payment_dict(p: Payment) -> dict:
    return {
        "id": str(p.id),
        "plan_type": p.plan_type,
        "amount": float(p.amount),
        "paid_amount": float(p.paid_amount) if p.paid_amount is not None else None,
        "status": p.status,
        "support_code": p.support_code,
        "subscription_applied": bool(getattr(p, "subscription_applied", False)),
        "manual_activated_at": p.manual_activated_at,
        "yumoney_label": p.yumoney_label,
        "created_at": p.created_at,
        "completed_at": p.completed_at,
    }


async def lookup_payment_by_support_code(db: AsyncSession, raw_code: str) -> dict | None:
    code = normalize_support_code(raw_code)
    if not code:
        return None
    result = await db.execute(select(Payment).where(Payment.support_code == code))
    payment = result.scalar_one_or_none()
    if not payment:
        # допускаем поиск без дефисов
        compact = code.replace("-", "")
        result = await db.execute(select(Payment).where(Payment.support_code.is_not(None)))
        for p in result.scalars().all():
            if (p.support_code or "").replace("-", "").upper() == compact:
                payment = p
                break
    if not payment:
        return None

    user_result = await db.execute(select(User).where(User.id == payment.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return None

    admin = is_user_admin(user)
    in_test = await user_in_test_mode(user, db)
    sub = await get_display_subscription(db, user, in_test_mode=in_test)
    return {
        "payment": _payment_dict(payment),
        "user": _user_brief(user, admin=admin, in_test=in_test, sub=sub),
        "needs_activation": (
            payment.status == "completed"
            and not bool(getattr(payment, "subscription_applied", False))
            and not admin
        ),
    }


async def activate_subscription_by_support_code(db: AsyncSession, raw_code: str) -> dict:
    from fastapi import HTTPException

    data = await lookup_payment_by_support_code(db, raw_code)
    if not data:
        raise HTTPException(status_code=404, detail="Код не найден")
    payment_id = data["payment"]["id"]
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one()
    user_result = await db.execute(select(User).where(User.id == payment.user_id))
    user = user_result.scalar_one()

    if is_user_admin(user):
        raise HTTPException(status_code=400, detail="Администратору подписка не нужна")

    if payment.status != "completed":
        raise HTTPException(status_code=400, detail=f"Платёж в статусе «{payment.status}», не completed")

    if payment.subscription_applied and not data.get("needs_activation"):
        # Уже применено — вернём текущее состояние
        return {**data, "status": "already_active"}

    plan = (payment.plan_type or "").strip().lower()
    sub = await grant_manual_subscription(db, user, plan)
    # grant_manual делает commit — перечитываем payment
    result = await db.execute(select(Payment).where(Payment.id == payment.id))
    payment = result.scalar_one()
    payment.subscription_applied = True
    payment.manual_activated_at = datetime.utcnow()
    await db.commit()

    refreshed = await lookup_payment_by_support_code(db, payment.support_code or raw_code)
    return {**(refreshed or data), "status": "activated", "expires_at": sub.expires_at}


async def list_orphan_payments(db: AsyncSession, limit: int = 30) -> list[dict]:
    """Оплаты completed без subscription_applied — кандидаты в поддержку."""
    result = await db.execute(
        select(Payment, User)
        .join(User, User.id == Payment.user_id)
        .where(
            Payment.status == "completed",
            Payment.subscription_applied.is_(False),
            Payment.support_code.is_not(None),
        )
        .order_by(Payment.completed_at.desc().nullslast(), Payment.created_at.desc())
        .limit(limit)
    )
    out = []
    for payment, user in result.all():
        out.append({
            "payment": _payment_dict(payment),
            "user": {
                "id": str(user.id),
                "display_id": user.display_id,
                "email": user.email,
            },
        })
    return out


async def list_subscription_users(
    db: AsyncSession,
    *,
    q: str = "",
    page: int = 1,
    page_size: int = 50,
    filter_mode: str = "all",
) -> dict:
    from app.services.test_mode_settings import is_registration_test_mode_enabled
    from app.config import settings

    global_test = await is_registration_test_mode_enabled(db)
    admin_email = settings.ADMIN_LOGIN.lower()
    page = max(1, page)
    qn = (q or "").strip().lower()
    # Поиск — все совпадения сразу (не «только текущая страница»).
    searching = bool(qn)
    page_size = min(500 if searching else 100, max(10, page_size if not searching else 500))
    offset = 0 if searching else (page - 1) * page_size

    base = select(User).where(User.email != BOOTSTRAP_EMAIL)
    if qn:
        like = f"%{qn}%"
        # display_id = str(uuid)[:8].upper() — в БД это не колонка, ищем по email и uuid
        uuid_text = cast(User.id, SAString)
        id8 = func.upper(func.substr(uuid_text, 1, 8))
        base = base.where(
            or_(
                func.lower(User.email).like(like),
                uuid_text.ilike(like),
                id8.like(f"%{qn.upper()}%"),
            )
        )

    count_q = select(func.count()).select_from(base.subquery())
    total_matched = int((await db.execute(count_q)).scalar_one() or 0)

    ordered = base.order_by(
        case_admin_first(admin_email),
        User.created_at.desc(),
    )

    if searching or filter_mode != "all":
        # Поиск / фильтр: берём весь подходящий набор (до 500), потом режем страницу только без q.
        fetch_limit = min(500, total_matched or 500)
        result = await db.execute(ordered.limit(fetch_limit))
        candidates = list(result.scalars().all())
        rows = await _build_user_rows(db, candidates, global_test)
        if filter_mode == "active":
            rows = [r for r in rows if r["subscription"]["active"]]
        elif filter_mode == "inactive":
            rows = [r for r in rows if not r["subscription"]["active"] and not r["is_admin"]]
        elif filter_mode == "unpaid":
            unpaid_ids = {
                str(uid)
                for uid, in (
                    await db.execute(
                        select(Payment.user_id)
                        .where(
                            Payment.status == "completed",
                            Payment.subscription_applied.is_(False),
                            Payment.support_code.is_not(None),
                        )
                        .distinct()
                    )
                ).all()
            }
            rows = [r for r in rows if r["id"] in unpaid_ids]
        total = len(rows)
        if searching:
            # Все найденные на одном экране
            return {
                "items": rows,
                "page": 1,
                "page_size": total or page_size,
                "total": total,
                "pages": 1,
            }
        users_page = rows[offset : offset + page_size]
        return {
            "items": users_page,
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    result = await db.execute(ordered.offset(offset).limit(page_size))
    users = list(result.scalars().all())
    items = await _build_user_rows(db, users, global_test)
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total_matched,
        "pages": max(1, (total_matched + page_size - 1) // page_size),
    }


def case_admin_first(admin_email: str):
    from sqlalchemy import case
    return case(
        ((User.is_admin == True) | (func.lower(User.email) == admin_email), 0),  # noqa: E712
        else_=1,
    )


async def _build_user_rows(db: AsyncSession, users: list[User], global_test: bool) -> list[dict]:
    if not users:
        return []
    user_ids = [u.id for u in users]
    subs_by_user: dict = {}
    for sub in (
        await db.execute(
            select(Subscription)
            .where(
                Subscription.user_id.in_(user_ids),
                Subscription.status == "active",
            )
            .order_by(Subscription.expires_at.desc())
        )
    ).scalars().all():
        subs_by_user.setdefault(sub.user_id, []).append(sub)

    pay_counts: dict = {}
    for uid, n in (
        await db.execute(
            select(Payment.user_id, func.count(Payment.id))
            .where(Payment.user_id.in_(user_ids), Payment.status == "completed")
            .group_by(Payment.user_id)
        )
    ).all():
        pay_counts[uid] = int(n)

    out = []
    for user in users:
        admin = is_user_admin(user)
        individual_test = bool(getattr(user, "test_mode_personal", False))
        excluded = bool(getattr(user, "test_mode_excluded", False))
        in_test = (not admin) and (individual_test or (global_test and not excluded))
        sub = None
        for candidate in subs_by_user.get(user.id, []):
            if not candidate.is_active:
                continue
            if candidate.plan_type == TEST_PLAN and not in_test:
                continue
            sub = candidate
            break
        brief = _user_brief(user, admin=admin, in_test=in_test, sub=sub)
        brief["payments_completed"] = pay_counts.get(user.id, 0)
        out.append(brief)
    return out


async def user_subscription_history(db: AsyncSession, user_id) -> dict:
    from fastapi import HTTPException
    import uuid

    uid = uuid.UUID(str(user_id))
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    admin = is_user_admin(user)
    in_test = await user_in_test_mode(user, db)
    sub = await get_display_subscription(db, user, in_test_mode=in_test)

    payments = (
        await db.execute(
            select(Payment)
            .where(Payment.user_id == uid)
            .order_by(Payment.created_at.desc())
            .limit(100)
        )
    ).scalars().all()

    subscriptions = (
        await db.execute(
            select(Subscription)
            .where(Subscription.user_id == uid)
            .order_by(Subscription.started_at.desc())
            .limit(100)
        )
    ).scalars().all()

    return {
        "user": _user_brief(user, admin=admin, in_test=in_test, sub=sub),
        "payments": [_payment_dict(p) for p in payments],
        "subscriptions": [
            {
                "id": str(s.id),
                "plan_type": s.plan_type,
                "status": s.status,
                "amount_paid": float(s.amount_paid),
                "started_at": s.started_at,
                "expires_at": s.expires_at,
                "is_active_now": s.is_active,
                "promo_code": s.promo_code,
            }
            for s in subscriptions
        ],
    }
