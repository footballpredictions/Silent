"""Unit tests: days_left должен показывать полный день включительно (триал 3→1)."""
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.subscription_kinds import compute_days_left  # noqa: E402
from app.services.yumoney_datetime import (  # noqa: E402
    parse_yumoney_datetime,
    yumoney_datetime_from_raw_response,
)


class DaysLeftTests(unittest.TestCase):
    def test_fresh_three_day_trial_shows_three(self):
        now = datetime(2026, 9, 7, 12, 0, 0)
        expires = now + timedelta(days=3)
        self.assertEqual(compute_days_left(expires, now), 3)

    def test_almost_one_day_elapsed_still_three(self):
        now = datetime(2026, 9, 7, 12, 0, 0)
        expires = now + timedelta(days=3)
        self.assertEqual(compute_days_left(expires, now + timedelta(days=1) - timedelta(seconds=1)), 3)

    def test_exactly_two_days_left(self):
        now = datetime(2026, 9, 7, 12, 0, 0)
        expires = now + timedelta(days=3)
        self.assertEqual(compute_days_left(expires, now + timedelta(days=1)), 2)

    def test_last_day_shows_one_not_zero(self):
        now = datetime(2026, 9, 7, 12, 0, 0)
        expires = now + timedelta(days=3)
        self.assertEqual(compute_days_left(expires, expires - timedelta(hours=12)), 1)
        self.assertEqual(compute_days_left(expires, expires - timedelta(seconds=1)), 1)

    def test_expired_is_zero(self):
        now = datetime(2026, 9, 7, 12, 0, 0)
        self.assertEqual(compute_days_left(now - timedelta(seconds=1), now), 0)
        self.assertEqual(compute_days_left(now, now), 0)

    def test_old_truncating_behavior_was_wrong(self):
        """Документируем регрессию: timedelta.days на старте триала давал 2."""
        now = datetime(2026, 9, 7, 12, 0, 0)
        expires = now + timedelta(days=3)
        almost = expires - timedelta(seconds=1)
        self.assertEqual((almost - now).days, 2)  # старый баг
        self.assertEqual(compute_days_left(expires, now + timedelta(seconds=1)), 3)


class YuMoneyDatetimePureTests(unittest.TestCase):
    def test_parse_zulu(self):
        self.assertEqual(parse_yumoney_datetime("2026-07-14T10:00:00Z"), datetime(2026, 7, 14, 10, 0, 0))

    def test_parse_from_raw_response_dict_repr(self):
        raw = str({"datetime": "2026-07-14T10:15:30Z", "label": "silent_x"})
        self.assertEqual(yumoney_datetime_from_raw_response(raw), datetime(2026, 7, 14, 10, 15, 30))

    def test_parse_empty(self):
        self.assertIsNone(parse_yumoney_datetime(""))
        self.assertIsNone(yumoney_datetime_from_raw_response(None))


if __name__ == "__main__":
    unittest.main()
