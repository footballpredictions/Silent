"""Fix paid plans that absorbed a pre-pay referral (+30d) into +90/+60/+30.

Пример бага: реф 27.08→26.09, оплата 3 мес → 26.09+90д=25.12 вместо 27.11 (+ реф до 27.12).

Dry-run:  python scripts/fix_referral_paid_stack_expires.py
Apply:    python scripts/fix_referral_paid_stack_expires.py --apply
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run  # noqa: E402

REMOTE_SCRIPT = "/tmp/fix_referral_paid_stack_expires_inner.py"

INNER = r'''
import asyncio
import json
import sys
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Subscription
from app.services.subscription_kinds import (
    LEGACY_PLAN_FIXED_DAYS,
    REFERRAL_PLAN,
    bonus_period_expires,
    plan_expires_at,
)

APPLY = "--apply" in sys.argv


async def main() -> None:
    now = datetime.utcnow()
    plans = tuple(LEGACY_PLAN_FIXED_DAYS.keys())
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.expires_at > now,
                Subscription.plan_type.in_(plans),
                Subscription.amount_paid > 0,
            )
        )
        paid_rows = list(result.scalars().all())
        would = []
        for sub in paid_rows:
            started = sub.started_at
            expires = sub.expires_at
            if not started or not expires:
                continue
            legacy = LEGACY_PLAN_FIXED_DAYS.get(sub.plan_type)
            if legacy is None:
                continue
            # Оплата «съела» реф: длина ≈ legacy + 30 суток (время базы может отличаться от started)
            span_days = (expires - started).total_seconds() / 86400.0
            if abs(span_days - (legacy + 30)) > 1.0:
                continue
            new_paid = plan_expires_at(started, sub.plan_type)
            new_ref = bonus_period_expires(new_paid, 30)
            # Не укорачиваем общий доступ
            if new_ref < expires - timedelta(seconds=2):
                continue
            would.append(
                {
                    "user_id": str(sub.user_id),
                    "plan": sub.plan_type,
                    "span_days": round(span_days, 2),
                    "started_at": started.isoformat(),
                    "old_paid_expires": expires.isoformat(),
                    "new_paid_expires": new_paid.isoformat(),
                    "new_referral_expires": new_ref.isoformat(),
                }
            )
            if not APPLY:
                continue
            sub.expires_at = new_paid
            # Активный реф-бонус до new_ref (стек поверх оплаты)
            ref_q = await db.execute(
                select(Subscription).where(
                    Subscription.user_id == sub.user_id,
                    Subscription.plan_type == REFERRAL_PLAN,
                ).order_by(Subscription.created_at.desc())
            )
            ref = ref_q.scalars().first()
            if ref:
                ref.status = "active"
                ref.expires_at = new_ref
                if ref.started_at is None:
                    ref.started_at = started
            else:
                db.add(
                    Subscription(
                        user_id=sub.user_id,
                        plan_type=REFERRAL_PLAN,
                        status="active",
                        amount_paid=0,
                        started_at=started,
                        expires_at=new_ref,
                    )
                )
        if APPLY and would:
            await db.commit()
        print(
            json.dumps(
                {
                    "apply": APPLY,
                    "scanned_paid_active": len(paid_rows),
                    "to_fix": len(would),
                    "sample": would[:20],
                },
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
        for rel in (
            "app/services/subscription_kinds.py",
            "app/services/payment_service.py",
            "app/services/referral_service.py",
        ):
            local = BACKEND_ROOT.joinpath(*rel.split("/"))
            sftp.put(str(local), f"{REMOTE}/{rel}")
        sftp.putfo(io.BytesIO(INNER.encode("utf-8")), REMOTE_SCRIPT)
        sftp.close()
        flag = " --apply" if args.apply else ""
        out = run(
            client,
            f"docker exec -i {CONTAINER} python - {flag} < {REMOTE_SCRIPT}",
            timeout=180,
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
