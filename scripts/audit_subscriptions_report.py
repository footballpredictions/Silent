"""Аудит живых подписок на Улье: сводка и подозрительные сроки.

Запуск из backend/: python scripts/audit_subscriptions_report.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _deploy_common import connect, load_env, run

QUERIES = [
    (
        "LIVE by kind",
        """
WITH live AS (
  SELECT DISTINCT ON (s.user_id)
    s.plan_type, s.amount_paid,
    CASE
      WHEN s.plan_type = 'trial' THEN 'trial'
      WHEN s.plan_type = 'test' THEN 'other'
      WHEN s.plan_type = 'referral_bonus' THEN 'referral'
      WHEN COALESCE(s.amount_paid,0) > 0 THEN 'paid'
      ELSE 'granted'
    END AS kind
  FROM subscriptions s
  WHERE s.status = 'active' AND s.expires_at > (now() AT TIME ZONE 'utc')
  ORDER BY s.user_id, s.expires_at DESC
)
SELECT kind, plan_type, count(*) AS users
FROM live GROUP BY kind, plan_type ORDER BY kind, plan_type;
""",
    ),
    (
        "LIVE totals",
        """
WITH live AS (
  SELECT DISTINCT ON (s.user_id)
    CASE
      WHEN s.plan_type = 'trial' THEN 'trial'
      WHEN s.plan_type = 'test' THEN 'other'
      WHEN s.plan_type = 'referral_bonus' THEN 'referral'
      WHEN COALESCE(s.amount_paid,0) > 0 THEN 'paid'
      ELSE 'granted'
    END AS kind
  FROM subscriptions s
  WHERE s.status = 'active' AND s.expires_at > (now() AT TIME ZONE 'utc')
  ORDER BY s.user_id, s.expires_at DESC
)
SELECT kind, count(*) FROM live GROUP BY kind ORDER BY kind;
""",
    ),
    (
        "Suspicious granted yearly (span>380d)",
        """
SELECT u.email, s.plan_type,
       to_char(s.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS started,
       to_char(s.expires_at AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS expires,
       ROUND(EXTRACT(EPOCH FROM (s.expires_at - s.started_at))/86400.0)::int AS span_days
FROM subscriptions s
JOIN users u ON u.id = s.user_id
WHERE s.status = 'active'
  AND s.expires_at > (now() AT TIME ZONE 'utc')
  AND s.plan_type = 'yearly'
  AND COALESCE(s.amount_paid,0) = 0
  AND s.expires_at > s.started_at + interval '380 days'
ORDER BY span_days DESC
LIMIT 40;
""",
    ),
    (
        "Zombie active+expired",
        "SELECT count(*) AS zombie FROM subscriptions WHERE status='active' AND expires_at <= (now() AT TIME ZONE 'utc');",
    ),
    (
        "Multi live rows",
        """
SELECT count(*) AS users_with_multi FROM (
  SELECT user_id FROM subscriptions
  WHERE status='active' AND expires_at > (now() AT TIME ZONE 'utc')
  GROUP BY user_id HAVING count(*) > 1
) t;
""",
    ),
]


def main() -> None:
    load_env()
    q = connect()
    for title, sql in QUERIES:
        print(f"\n=== {title} ===")
        b64 = base64.b64encode(sql.encode()).decode()
        run(
            q,
            f"echo {b64} | base64 -d > /tmp/aud.sql && "
            f"docker cp /tmp/aud.sql backend-db-1:/tmp/aud.sql && "
            f"docker exec backend-db-1 psql -U silent -d silent_vpn -f /tmp/aud.sql",
            timeout=60,
        )
    q.close()


if __name__ == "__main__":
    main()
