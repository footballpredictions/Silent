"""Run the actual browser payment poll with controlled API replies and timers."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const text = fs.readFileSync('web/js/app.js', 'utf8');
const source = text.slice(text.indexOf('let paymentPollVersion ='), text.indexOf('async function pickServer'));
async function run(first, cancel = false) {
  let count = 0, clock = 0;
  const paid = { subscription: { is_active: true, plan_type: 'monthly_5' }, max_devices: 5 };
  const ctx = {
    state: { paymentStatus: 'waiting', profile: { subscription: { is_active: false }, max_devices: 3 } },
    Date: { now: () => clock },
    setTimeout: resolve => { clock += 4000; resolve() },
    render() {},
    api: {
      paymentStatus: async () => ({ status: 'completed', subscription_applied: true, plan_type: 'monthly_5' }),
      profile: async () => {
        count++;
        assert.equal(ctx.state.paymentStatus, 'waiting', 'success must follow the fresh profile');
        if (cancel) vm.runInContext('paymentPollVersion++', ctx);
        if (count === 1 && first === 'error') throw Error('temporary network loss');
        return count === 1 && first === 'inactive' ? { subscription: { is_active: false } } : paid;
      },
    },
  };
  vm.createContext(ctx);
  vm.runInContext(source, ctx);
  await vm.runInContext('pollPayment("paid-label", 0)', ctx);
  if (cancel) {
    assert.equal(ctx.state.paymentStatus, 'waiting');
    assert.equal(ctx.state.profile.max_devices, 3);
  } else {
    assert.equal(ctx.state.paymentStatus, 'completed');
    assert.equal(ctx.state.profile.max_devices, 5);
    assert.equal(count, first === 'paid' ? 1 : 2);
  }
}
(async () => {
  await run('paid'); await run('error'); await run('inactive'); await run('paid', true);
  console.log('payment profile: 4 scenarios passed');
})().catch(error => { console.error(error); process.exitCode = 1 });
"""


class PaymentProfileTests(unittest.TestCase):
    def test_confirmed_payment_refreshes_profile_before_success_and_retries(self):
        result = subprocess.run(["node", "-e", SCRIPT], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
