"""Bump active referral_bonus short by 1–2 days after paid calendar backfill.

Пример: месяц 27.08→27.09, реф был до 26.10 (+30 от старого 26.09) → должно 27.10.

Dry-run:  python scripts/fix_referral_on_paid_calendar.py
Apply:    python scripts/fix_referral_on_paid_calendar.py --apply
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run  # noqa: E402

REMOTE_SCRIPT = "/tmp/fix_referral_on_paid_calendar_inner.py"

INNER = r'''
import asyncio
import json
import sys
from datetime import timedelta

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Subscription
from app.services.subscription_kinds import (
    PLAN_CALENDAR_MONTHS,
    REFERRAL_PLAN,
    bonus_period_expires,
)

APPLY = "--apply" in sys.argv
MAX_BUMP_DAYS = 3


async def main() -> None:
    async with AsyncSessionLocal() as db:
        paid_q = await db.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.amount_paid > 0,
                Subscription.plan_type.in_(tuple(PLAN_CALENDAR_MONTHS.keys())),
            )
        )
        paid_by_user = {}
        for s in paid_q.scalars().all():
            cur = paid_by_user.get(s.user_id)
            if cur is None or (s.expires_at and cur.expires_at and s.expires_at > cur.expires_at):
                paid_by_user[s.user_id] = s

        ref_q = await db.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.plan_type == REFERRAL_PLAN,
            )
        )
        would = []
        for ref in ref_q.scalars().all():
            paid = paid_by_user.get(ref.user_id)
            if not paid or not paid.expires_at or not ref.expires_at:
                continue
            expected = bonus_period_expires(paid.expires_at, 30)
            delta = expected - ref.expires_at
            if delta.total_seconds() <= 2:
                continue
            if delta > timedelta(days=MAX_BUMP_DAYS):
                continue
            would.append(
                {
                    "user_id": str(ref.user_id),
                    "paid_plan": paid.plan_type,
                    "paid_expires": paid.expires_at.isoformat(),
                    "old_ref_expires": ref.expires_at.isoformat(),
                    "new_ref_expires": expected.isoformat(),
                    "delta_days": round(delta.total_seconds() / 86400, 2),
                }
            )
            if APPLY:
                ref.expires_at = expected
        if APPLY and would:
            await db.commit()
        print(
            json.dumps(
                {"apply": APPLY, "to_fix": len(would), "sample": would},
                ensure_ascii=False,
            )
        )


asyncio.run(main())
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    client = connect()
    try:
        sftp = client.open_sftp()
        local = BACKEND_ROOT / "app" / "services" / "subscription_kinds.py"
        sftp.put(str(local), f"{REMOTE}/app/services/subscription_kinds.py")
        sftp.putfo(io.BytesIO(INNER.encode("utf-8")), REMOTE_SCRIPT)
        sftp.close()
        flag = " --apply" if args.apply else ""
        out = run(
            client,
            f"docker exec -i {CONTAINER} python - {flag} < {REMOTE_SCRIPT}",
            timeout=120,
        )
        for line in reversed(out.strip().splitlines()):
            if line.strip().startswith("{"):
                print("\n=== summary ===")
                print(json.dumps(json.loads(line.strip()), ensure_ascii=False, indent=2))
                break
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
