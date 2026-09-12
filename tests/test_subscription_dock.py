import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.silent_subscription import dock_kind, has_vpn_access, is_unlimited_like


class SubscriptionDockTests(unittest.TestCase):
    def test_admin_is_unlimited_not_days(self):
        admin = {
            "is_admin": True,
            "subscription": {"is_active": True, "plan_type": "trial", "days_left": 9999},
        }
        self.assertEqual(dock_kind(admin), "unlimited")
        self.assertTrue(is_unlimited_like(admin))
        self.assertTrue(has_vpn_access(admin))

    def test_unpaid_gets_pay_button(self):
        user = {"is_admin": False, "subscription": {"is_active": False, "days_left": 0}}
        self.assertEqual(dock_kind(user), "pay")
        self.assertFalse(has_vpn_access(user))

    def test_trial_and_paid(self):
        trial = {"subscription": {"is_active": True, "plan_type": "trial", "days_left": 3}}
        paid = {"subscription": {"is_active": True, "plan_type": "monthly", "days_left": 20}}
        self.assertEqual(dock_kind(trial), "trial")
        self.assertEqual(dock_kind(paid), "paid")


if __name__ == "__main__":
    unittest.main()
