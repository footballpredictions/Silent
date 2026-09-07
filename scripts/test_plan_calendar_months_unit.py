"""Календарные месяцы для планов: 7.09 + 2 мес = 7.11, не 6.11 от 60 суток."""
from datetime import datetime
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.subscription_kinds import (  # noqa: E402
    add_calendar_months,
    plan_expires_at,
    suggest_calendar_expires_fix,
    CALENDAR_MONTHS_DEPLOY_CUTOFF_UTC,
)


class CalendarMonthsTests(unittest.TestCase):
    def test_user_report_two_months_same_day(self):
        base = datetime(2026, 9, 7, 12, 0, 0)
        self.assertEqual(plan_expires_at(base, "monthly").date(), datetime(2026, 10, 7).date())
        self.assertEqual(plan_expires_at(base, "two_months").date(), datetime(2026, 11, 7).date())
        self.assertEqual(plan_expires_at(base, "quarterly").date(), datetime(2026, 12, 7).date())

    def test_old_60_days_was_wrong(self):
        base = datetime(2026, 9, 7, 12, 0, 0)
        from datetime import timedelta
        self.assertEqual((base + timedelta(days=60)).date(), datetime(2026, 11, 6).date())

    def test_month_end_clamp(self):
        base = datetime(2026, 1, 31, 15, 30, 0)
        feb = add_calendar_months(base, 1)
        self.assertEqual(feb, datetime(2026, 2, 28, 15, 30, 0))

    def test_jan31_non_leap_to_feb28(self):
        self.assertEqual(
            plan_expires_at(datetime(2026, 1, 31, 12, 0, 0), "monthly"),
            datetime(2026, 2, 28, 12, 0, 0),
        )

    def test_jan31_leap_to_feb29(self):
        self.assertEqual(
            plan_expires_at(datetime(2024, 1, 31, 12, 0, 0), "monthly"),
            datetime(2024, 2, 29, 12, 0, 0),
        )

    def test_mar31_to_apr30(self):
        self.assertEqual(
            plan_expires_at(datetime(2026, 3, 31, 9, 0, 0), "monthly"),
            datetime(2026, 4, 30, 9, 0, 0),
        )

    def test_jan31_two_months_lands_on_mar31(self):
        # янв→мар: 31 есть; не «потерять» день из‑за февраля
        self.assertEqual(
            plan_expires_at(datetime(2026, 1, 31, 12, 0, 0), "two_months"),
            datetime(2026, 3, 31, 12, 0, 0),
        )

    def test_feb29_leap_yearly_to_feb28(self):
        self.assertEqual(
            plan_expires_at(datetime(2024, 2, 29, 12, 0, 0), "yearly"),
            datetime(2025, 2, 28, 12, 0, 0),
        )

    def test_aug31_to_sep30(self):
        self.assertEqual(
            plan_expires_at(datetime(2026, 8, 31, 12, 0, 0), "monthly"),
            datetime(2026, 9, 30, 12, 0, 0),
        )

    def test_three_days_still_fixed(self):
        base = datetime(2026, 9, 7, 12, 0, 0)
        self.assertEqual(plan_expires_at(base, "three_days").date(), datetime(2026, 9, 10).date())

    def test_preserves_time_of_day(self):
        base = datetime(2026, 9, 7, 18, 45, 12)
        out = plan_expires_at(base, "two_months")
        self.assertEqual(out, datetime(2026, 11, 7, 18, 45, 12))

    def test_backfill_two_months_extends_to_same_day(self):
        from datetime import timedelta
        started = datetime(2026, 9, 7, 12, 0, 0)
        old_exp = started + timedelta(days=60)
        fixed = suggest_calendar_expires_fix(
            plan_type="two_months", started_at=started, expires_at=old_exp
        )
        self.assertEqual(fixed, datetime(2026, 11, 7, 12, 0, 0))

    def test_backfill_idempotent_after_fix(self):
        started = datetime(2026, 9, 7, 12, 0, 0)
        fixed_once = plan_expires_at(started, "two_months")
        self.assertIsNone(
            suggest_calendar_expires_fix(
                plan_type="two_months", started_at=started, expires_at=fixed_once
            )
        )

    def test_backfill_skips_after_cutoff(self):
        after = CALENDAR_MONTHS_DEPLOY_CUTOFF_UTC
        from datetime import timedelta
        self.assertIsNone(
            suggest_calendar_expires_fix(
                plan_type="two_months",
                started_at=after,
                expires_at=after + timedelta(days=60),
            )
        )

    def test_backfill_never_shortens(self):
        from datetime import timedelta
        started = datetime(2026, 1, 31, 12, 0, 0)
        old_exp = started + timedelta(days=30)
        self.assertIsNone(
            suggest_calendar_expires_fix(
                plan_type="monthly", started_at=started, expires_at=old_exp
            )
        )


if __name__ == "__main__":
    unittest.main()
