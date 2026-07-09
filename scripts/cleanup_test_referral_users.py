"""Delete smoke/test referral users from production DB (run inside api container)."""
from __future__ import annotations

import asyncio
from sqlalchemy import delete, select, or_, text

from app.database import AsyncSessionLocal
from app.models import User, ReferralReward, Payment, Subscription, Device, VkHash, VkLinkSession


async def main() -> None:
    async with AsyncSessionLocal() as db:
        # Patterns from smoke_referral.py / remote_referral_db_test.py
        result = await db.execute(
            select(User).where(
                or_(
                    User.email.ilike("ref.%@example.com"),
                    User.email.ilike("ref_inv_%@%"),
                    User.email.ilike("ref_invtee_%@%"),
                    User.email.ilike("ref_bad_%@%"),
                    User.email.ilike("ref_ok_%@%"),
                    User.email.ilike("ref.inv.%@example.com"),
                    User.email.ilike("ref.tee.%@example.com"),
                    User.email.ilike("ref.bad.%@example.com"),
                    User.email.ilike("ref.ok.%@example.com"),
                )
            )
        )
        users = list(result.scalars().all())
        print(f"FOUND {len(users)}")
        for u in users:
            print(f"  {u.email} {u.id}")

        ids = [u.id for u in users]
        if not ids:
            print("NOTHING_TO_DELETE")
            return

        # Clear FK refs from other users
        await db.execute(
            text(
                "UPDATE users SET referred_by_user_id = NULL "
                "WHERE referred_by_user_id = ANY(:ids)"
            ),
            {"ids": ids},
        )
        await db.execute(
            delete(ReferralReward).where(
                or_(
                    ReferralReward.inviter_id.in_(ids),
                    ReferralReward.invitee_id.in_(ids),
                )
            )
        )
        await db.execute(delete(VkHash).where(VkHash.user_id.in_(ids)))
        await db.execute(delete(VkLinkSession).where(VkLinkSession.user_id.in_(ids)))
        await db.execute(delete(Device).where(Device.user_id.in_(ids)))
        await db.execute(delete(Payment).where(Payment.user_id.in_(ids)))
        await db.execute(delete(Subscription).where(Subscription.user_id.in_(ids)))
        await db.execute(delete(User).where(User.id.in_(ids)))
        await db.commit()
        print(f"DELETED {len(ids)}")


if __name__ == "__main__":
    asyncio.run(main())
