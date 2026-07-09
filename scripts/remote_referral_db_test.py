"""Run inside backend-api-1 container: full referral reward simulation."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select, func, text
from app.database import AsyncSessionLocal
from app.models import User, ReferralReward, Payment, Subscription
from app.services.referral_service import (
    generate_unique_referral_code,
    bind_referral_on_register,
    apply_referral_reward_after_payment,
    get_referral_stats,
)
from app.core.security import hash_password


async def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT referral_code FROM users LIMIT 1"))

        inv = User(
            email=f"ref.inv.{suffix}@example.com",
            password_hash=hash_password("TestPass12!"),
            is_verified=True,
            is_active=True,
            referral_code=await generate_unique_referral_code(db),
        )
        db.add(inv)
        await db.flush()

        tee = User(
            email=f"ref.tee.{suffix}@example.com",
            password_hash=hash_password("TestPass12!"),
            is_verified=True,
            is_active=True,
            referral_code=await generate_unique_referral_code(db),
        )
        db.add(tee)
        await db.flush()
        await bind_referral_on_register(db, tee, inv, None)
        await db.commit()

        stats = await get_referral_stats(db, inv)
        assert stats["pending_count"] >= 1, stats
        assert stats["referral_link"].startswith("silentvpn://ref?code=")

        pay = Payment(
            user_id=tee.id,
            plan_type="monthly",
            amount=199,
            wallet="x",
            yumoney_label=f"silent_test_{suffix}",
            status="completed",
            completed_at=datetime.utcnow(),
        )
        db.add(pay)
        await db.commit()

        ok = await apply_referral_reward_after_payment(db, pay)
        assert ok is True, "reward should apply on first payment"

        stats2 = await get_referral_stats(db, inv)
        assert stats2["rewarded_count"] >= 1, stats2

        pending = await db.execute(
            select(func.count())
            .select_from(ReferralReward)
            .where(
                ReferralReward.invitee_id == tee.id,
                ReferralReward.status == "pending",
            )
        )
        assert int(pending.scalar_one() or 0) == 0

        # both users should have referral_bonus subscription rows
        for uid, label in ((tee.id, "invitee"), (inv.id, "inviter")):
            subs = await db.execute(
                select(Subscription).where(
                    Subscription.user_id == uid,
                    Subscription.plan_type == "referral_bonus",
                    Subscription.status == "active",
                )
            )
            rows = list(subs.scalars().all())
            assert rows, f"missing referral_bonus for {label}"

        print("REFERRAL_DB_OK", stats["referral_code"], stats2["rewarded_count"])


if __name__ == "__main__":
    asyncio.run(main())
