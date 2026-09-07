"""One-shot: bump legacy fixed-day plan expires to calendar months (prod).

Dry-run по умолчанию. Применить: --apply

  python scripts/fix_subscription_calendar_expires.py
  python scripts/fix_subscription_calendar_expires.py --apply
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import BACKEND_ROOT, CONTAINER, REMOTE, connect, run  # noqa: E402

REMOTE_SCRIPT = "/tmp/fix_subscription_calendar_expires_inner.py"

INNER = r'''
import asyncio
import json
import sys
from datetime import datetime

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Subscription
from app.services.subscription_kinds import (
    LEGACY_PLAN_FIXED_DAYS,
    suggest_calendar_expires_fix,
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
            )
        )
        rows = list(result.scalars().all())
        would = []
        for sub in rows:
            new_exp = suggest_calendar_expires_fix(
                plan_type=sub.plan_type,
                started_at=sub.started_at,
                expires_at=sub.expires_at,
            )
            if new_exp is None:
                continue
            would.append(
                {
                    "id": str(sub.id),
                    "user_id": str(sub.user_id),
                    "plan": sub.plan_type,
                    "started_at": sub.started_at.isoformat() if sub.started_at else None,
                    "old_expires": sub.expires_at.isoformat() if sub.expires_at else None,
                    "new_expires": new_exp.isoformat(),
                    "delta_days": round((new_exp - sub.expires_at).total_seconds() / 86400, 2),
                }
            )
            if APPLY:
                sub.expires_at = new_exp
        if APPLY and would:
            await db.commit()
        by_plan = {}
        for w in would:
            by_plan[w["plan"]] = by_plan.get(w["plan"], 0) + 1
        print(
            json.dumps(
                {
                    "apply": APPLY,
                    "scanned_active": len(rows),
                    "to_fix": len(would),
                    "by_plan": by_plan,
                    "sample": would[:15],
                },
                ensure_ascii=False,
            )
        )


asyncio.run(main())
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Записать в БД (иначе только dry-run)")
    args = ap.parse_args()

    client = connect()
    try:
        sftp = client.open_sftp()
        local_kinds = BACKEND_ROOT / "app" / "services" / "subscription_kinds.py"
        sftp.put(str(local_kinds), f"{REMOTE}/app/services/subscription_kinds.py")
        sftp.putfo(io.BytesIO(INNER.encode("utf-8")), REMOTE_SCRIPT)
        sftp.close()
        print("uploaded subscription_kinds.py + inner script")

        flag = " --apply" if args.apply else ""
        out = run(
            client,
            f"docker exec -i {CONTAINER} python - {flag} < {REMOTE_SCRIPT}",
            timeout=180,
        )
        for line in reversed(out.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                print("\n=== summary ===")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                break
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
