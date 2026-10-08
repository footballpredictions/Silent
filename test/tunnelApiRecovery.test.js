const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

function harness(errors, settling = false) {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const callback = source.match(/ipcMain.handle\('tunnel-api-request', (async \(_, payload\) => \{[\s\S]*?\n\})\)/)[1]
  const refused = source.match(/function isTunnelApiRefused\(err\) \{[\s\S]*?\n\}/)[0]
  const state = {
    clock: 100000,
    tunnelCalls: 0,
    publicCalls: 0,
    wgApplied: true, tunnelApiDown: false, tunnelApiRetryAfter: 0,
    captchaInProgress: false, apiQuietUntil: 0,
    wgRouteSettleUntil: settling ? 115000 : 0,
    wgFullTunnelUpgradeInFlight: false, wgCredPhase: false,
    isOlcrtc2ApiPath: () => false, shouldLogTunnelApiFallback: () => false,
    sendLog() {}, ensurePublicApiBypass: async () => {}, sleep: async () => {},
    async tunnelHttpRequest() {
      state.tunnelCalls++
      const error = errors.shift()
      if (error) throw Object.assign(new Error(error), { code: error })
      return { status: 200, data: { source: 'tunnel' } }
    },
    async publicDirectRequest() {
      state.publicCalls++
      return { status: 200, data: { source: 'public' } }
    },
  }
  state.Date = { now: () => state.clock }
  const handler = vm.runInNewContext(`${refused}\n(${callback})`, state)
  return { state, request: (payload = {}) => handler({}, { path: '/api/users/me', ...payload }) }
}

test('transient tunnel reset retries through VPN instead of latching public API', async () => {
  const { state, request } = harness(['ECONNRESET'], true)
  assert.equal((await request()).data.source, 'tunnel')
  assert.equal(state.tunnelCalls, 2)
  assert.equal(state.publicCalls, 0)
  assert.equal(state.tunnelApiDown, false)
})

test('real cell refusal retains public fallback but rechecks the tunnel later', async () => {
  const { state, request } = harness(['ECONNREFUSED'])
  assert.equal((await request()).data.source, 'public')
  assert.equal((await request()).data.source, 'public')
  assert.equal(state.tunnelCalls, 1, 'keep the short fallback window for cells without tunnel API')
  state.clock += 31000
  assert.equal((await request()).data.source, 'tunnel')
  assert.equal(state.tunnelCalls, 2)
  assert.equal(state.tunnelApiDown, false)
})

test('startup refusal retries tunnel while WireGuard routes are settling', async () => {
  const { state, request } = harness(['ECONNREFUSED'], true)
  assert.equal((await request()).data.source, 'tunnel')
  assert.equal(state.tunnelCalls, 2)
  assert.equal(state.publicCalls, 0)
  assert.equal(state.tunnelApiDown, false)
})

test('GET started before VPN recovers over the newly ready tunnel when its public chain fails', async () => {
  const { state, request } = harness([])
  state.wgApplied = false
  state.publicDirectRequest = async () => {
    state.publicCalls++
    // ConfigSync was already awaiting public HTTP when VPN routes appeared.
    state.wgApplied = true
    throw new Error('All public API bases failed')
  }
  assert.equal((await request({ path: '/api/vpn/sync-state' })).data.source, 'tunnel')
  assert.equal(state.tunnelCalls, 1)
  assert.equal(state.publicCalls, 1)
})

test('failed public fallback rechecks a refused tunnel immediately rather than keeping a dead fallback for 30 seconds', async () => {
  const { state, request } = harness(['ECONNREFUSED'])
  state.publicDirectRequest = async () => {
    state.publicCalls++
    throw new Error('All public API bases failed')
  }
  assert.equal((await request()).data.source, 'tunnel')
  assert.equal(state.tunnelCalls, 2)
  assert.equal(state.publicCalls, 1)
  assert.equal(state.tunnelApiDown, false)
})

test('an interrupted payment POST is not replayed automatically after a public failure', async () => {
  const { state, request } = harness([])
  state.wgApplied = false
  state.publicDirectRequest = async () => {
    state.publicCalls++
    state.wgApplied = true
    throw new Error('All public API bases failed')
  }
  await assert.rejects(request({ method: 'POST', path: '/api/payments/init' }), /All public API bases failed/)
  assert.equal(state.tunnelCalls, 0)
})

test('when public and tunnel both fail, keep the real failure and bound recovery attempts', async () => {
  const { state, request } = harness(['ECONNREFUSED', 'ECONNREFUSED'])
  state.publicDirectRequest = async () => {
    state.publicCalls++
    throw new Error('All public API bases failed')
  }
  await assert.rejects(request(), /All public API bases failed/)
  assert.equal(state.tunnelCalls, 2)
  assert.equal(state.publicCalls, 1)
})
