const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

function paymentFixture(payment = { status: 'completed', subscription_applied: true, plan_type: 'monthly_5' }) {
  const source = fs.readFileSync(path.join(__dirname, '../src/renderer/pages/MainScreen.tsx'), 'utf8').replace(/\r\n/g, '\n')
  const start = source.indexOf('  const startPaymentPoll =')
  const end = source.indexOf('\n\n  useEffect', start)
  const code = ts.transpileModule(source.slice(start, end), {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText
  let tick, status, stopCount = 0, profile = null
  let response = { subscription: { is_active: true, plan_type: 'monthly_5' }, max_devices: 5 }
  let resolveProfile, rejectProfile
  const pending = new Promise((resolve, reject) => { resolveProfile = resolve; rejectProfile = reject })
  const context = {
    useCallback: fn => fn,
    stopPaymentPoll() { context.paymentPollVersionRef.current++ }, setPaymentStatus(value) { status = value },
    paymentPollDeadlineRef: { current: 0 }, paymentPollRef: { current: null },
    setInterval(fn) { tick = fn; return 1 }, Date,
    document: { hidden: false },
    api: { get: async url => url.includes('/payments/status/')
      ? { data: payment }
      : { data: await pending } },
    applyServerProfile(value) { profile = value }, saveVkUserId() {},
    isPaymentBootstrapActive: () => true,
    stopPaymentBootstrapVpn: async () => { stopCount++ },
    paymentPollVersionRef: { current: 0 },
  }
  vm.runInNewContext(`${code}\nstartPaymentPoll('paid-label')`, context)
  return {
    tick: () => tick(), resolve: value => resolveProfile(value === undefined ? response : value),
    reject: () => rejectProfile(Error('network loss')),
    get status() { return status }, get stopCount() { return stopCount }, get profile() { return profile },
    context,
  }
}

test('payment success waits for the live profile before publishing success and stopping its VPN', async () => {
  const f = paymentFixture()
  const polling = f.tick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(f.status, 'waiting', 'the success effect must not tear down the VPN during profile loading')
  assert.equal(f.stopCount, 0)
  f.resolve()
  await polling
  assert.equal(f.status, 'completed')
  assert.equal(f.profile.subscription.is_active, true)
  assert.equal(f.profile.max_devices, 5)
  assert.equal(f.stopCount, 1)
})

test('stale or failed profile refresh keeps payment polling and its working VPN', async () => {
  const f = paymentFixture()
  const polling = f.tick()
  f.resolve({ subscription: { is_active: false, plan_type: null }, max_devices: 3 })
  await polling
  assert.equal(f.status, 'waiting')
  assert.equal(f.stopCount, 0)
})

test('network failure during profile loading retries without cached success', async () => {
  const f = paymentFixture()
  const polling = f.tick()
  await new Promise(resolve => setImmediate(resolve))
  f.reject()
  await polling
  assert.equal(f.status, 'waiting')
  assert.equal(f.profile, null)
  assert.equal(f.stopCount, 0)
})

test('cancellation while profile loads cannot publish late success or stop a new payment VPN', async () => {
  const f = paymentFixture()
  const polling = f.tick()
  await new Promise(resolve => setImmediate(resolve))
  f.context.stopPaymentPoll()
  f.resolve()
  await polling
  assert.equal(f.status, 'waiting')
  assert.equal(f.profile, null)
  assert.equal(f.stopCount, 0)
})

test('overlapping timer ticks do not duplicate completion or VPN teardown', async () => {
  const f = paymentFixture()
  const polling = f.tick()
  await f.tick()
  f.resolve()
  await polling
  assert.equal(f.stopCount, 1)
})

test('old trial or a different paid tier cannot complete a newly purchased plan', async () => {
  for (const plan of ['trial', 'monthly']) {
    const f = paymentFixture()
    const polling = f.tick()
    f.resolve({ subscription: { is_active: true, plan_type: plan }, max_devices: 3 })
    await polling
    assert.equal(f.status, 'waiting')
    assert.equal(f.stopCount, 0)
  }
})

test('successful payment in the background updates profile but keeps browser internet', async () => {
  const f = paymentFixture()
  f.context.document.hidden = true
  const polling = f.tick()
  f.resolve()
  await polling
  assert.equal(f.profile.max_devices, 5)
  assert.equal(f.status, 'completed')
  assert.equal(f.stopCount, 0)
})

test('webhook activation pending keeps waiting without fetching a profile', async () => {
  const f = paymentFixture({ status: 'completed', subscription_applied: false })
  await f.tick()
  assert.equal(f.status, 'waiting')
  assert.equal(f.profile, null)
  assert.equal(f.stopCount, 0)
})
