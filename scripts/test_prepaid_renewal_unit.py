"""Prepaid renewal specification, exercised through the shared quote interface."""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class RenewalTests(unittest.TestCase):
    def current(self, **changes):
        data = dict(plan_type="monthly", status="active", amount_paid=199,
                    started_at=datetime(2026, 9, 1), expires_at=datetime(2026, 10, 1),
                    renewal_daily_rate=None)
        data.update(changes)
        return SimpleNamespace(**data)

    def quote(self, current=None, **changes):
        from app.services.subscription_renewal import quote_renewal
        data = dict(now=datetime(2026, 9, 16), plan_type="monthly_5", amount=330,
                    prices={"monthly": (199, 30), "monthly_5": (330, 30), "quarterly_5": (792, 90)},
                    subscriptions=[] if current is None else [current])
        data.update(changes)
        return quote_renewal(**data)

    def test_upgrade_converts_fifteen_days_to_nine_without_changing_price(self):
        from app.services.subscription_renewal import quote_renewal

        current = SimpleNamespace(
            plan_type="monthly", status="active", amount_paid=199,
            started_at=datetime(2026, 9, 1), expires_at=datetime(2026, 10, 1),
            renewal_daily_rate=None,
        )
        quote = quote_renewal(
            now=datetime(2026, 9, 16), plan_type="monthly_5", amount=330,
            prices={"monthly": (199, 30), "monthly_5": (330, 30)},
            subscriptions=[current],
        )
        self.assertEqual(quote.amount, 330)
        self.assertAlmostEqual(quote.carried_days, 9.0454545, places=6)
        self.assertEqual(quote.expires_at, datetime(2026, 10, 25, 1, 5, 27))
        self.assertEqual(quote.new_devices, 5)

    def test_same_device_count_keeps_all_days_and_calendar_month(self):
        result = self.quote(self.current(), plan_type="monthly", amount=199)
        self.assertEqual(result.expires_at, datetime(2026, 11, 1))
        self.assertEqual(result.carried_days, 15)

    def test_repeated_prepayment_preserves_earlier_value(self):
        renewed = self.quote(self.current(), plan_type="monthly", amount=199)
        row = self.current(started_at=datetime(2026, 9, 16), expires_at=renewed.expires_at,
                           renewal_daily_rate=renewed.daily_rate)
        upgraded = self.quote(row)
        self.assertAlmostEqual(upgraded.carried_days, 27.1363636, places=6)
        self.assertEqual(upgraded.expires_at, datetime(2026, 11, 12, 3, 16, 21))

    def test_discounted_old_purchase_is_valued_at_paid_price(self):
        result = self.quote(self.current(amount_paid=99.5))
        self.assertAlmostEqual(result.carried_days, 4.52272727, places=6)
        self.assertEqual(result.amount, 330)

    def test_trial_and_expired_subscriptions_do_not_add_credit(self):
        for row in (self.current(plan_type="trial"), self.current(status="cancelled"),
                    self.current(expires_at=datetime(2026, 9, 15))):
            with self.subTest(row=row):
                result = self.quote(row)
                self.assertEqual(result.carried_days, 0)
                self.assertEqual(result.expires_at, datetime(2026, 10, 16))

    def test_same_tier_renewal_at_end_of_january_handles_leap_year(self):
        result = self.quote(self.current(started_at=datetime(2024, 1, 1), expires_at=datetime(2024, 1, 31)),
                            now=datetime(2024, 1, 16), plan_type="monthly", amount=199)
        self.assertEqual(result.expires_at, datetime(2024, 2, 29))

    def test_upgrade_and_downgrade_do_not_create_value(self):
        upgraded = self.quote(self.current())
        downgraded = self.quote(self.current(plan_type="monthly_5", amount_paid=330,
                               started_at=datetime(2026, 9, 16), expires_at=upgraded.expires_at,
                               renewal_daily_rate=upgraded.daily_rate), plan_type="monthly", amount=199)
        self.assertAlmostEqual(downgraded.carried_days, 64.7487437, places=5)

    def test_legacy_stack_is_not_valued_as_just_one_payment(self):
        result = self.quote(self.current(expires_at=datetime(2026, 11, 1)))
        self.assertAlmostEqual(result.carried_days, 27.7393939, places=6)

    def test_quarterly_upgrade_identifies_purchase_and_adds_both_periods(self):
        result = self.quote(self.current(plan_type="quarterly", amount_paid=478,
                            started_at=datetime(2026, 9, 28), expires_at=datetime(2026, 12, 28)),
                            now=datetime(2026, 9, 28), plan_type="quarterly_5", amount=792,
                            prices={"quarterly": (478, 90), "quarterly_5": (792, 90)})
        self.assertEqual(result.expires_at, datetime(2027, 2, 20, 22, 7, 16))
        data = result.as_dict()
        self.assertEqual(data["plan_type"], "quarterly_5")
        self.assertEqual(data["purchased_days"], 91)
        self.assertIn("3 месяца", data["message"])
        self.assertIn("91", data["message"])

    def test_warning_uses_whole_days_without_discarding_paid_value(self):
        result = self.quote(self.current())
        data = result.as_dict()
        self.assertIsInstance(data["carried_days"], int)
        self.assertEqual(data["carried_days"], 10)
        self.assertIn("30 дн. покупки + 10 дн. остатка", data["message"])
        self.assertNotRegex(data["message"], r"\d+\.\d+ дн")
        self.assertEqual(result.expires_at, datetime(2026, 10, 25, 1, 5, 27))


if __name__ == "__main__":
    unittest.main()
