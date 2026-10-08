const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const failover = require('../src/main/vpn/apiFailover')

test('public API uses the configured hive IP when nip.io DNS is unavailable, keeping HTTPS Host and SNI', async () => {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const start = source.indexOf('function publicDirectRequest(')
  const end = source.indexOf('\nfunction tunnelHttpRequest(', start)
  const calls = [], logs = []
  const request = vm.runInNewContext(`(${source.slice(start, end)})`, {
    ...failover, URL,
    UPDATE_HOST: '89-125-188-100.nip.io', SERVER_IP_FALLBACK: '89.125.188.100',
    hivePublicSlowUntil: 0,
    getPublicFailoverBases: () => ['https://89-125-188-100.nip.io', 'https://89.125.188.100:2083'],
    sendLog: line => logs.push(line),
    async backendHttpRequest(opts) {
      calls.push(opts)
      if (opts.hostname.endsWith('.nip.io')) throw new Error('getaddrinfo ENOTFOUND ' + opts.hostname)
      return { status: 200, data: { ok: true } }
    },
  })
  assert.equal((await request({ path: '/api/health' })).status, 200)
  assert.equal(calls.length, 1, 'the first HTTPS attempt must not depend on nip.io DNS')
  assert.equal(calls[0].hostname, '89.125.188.100')
  assert.equal(calls[0].port, 443)
  assert.equal(calls[0].headers.Host, '89-125-188-100.nip.io')
  assert.equal(calls[0].servername, '89-125-188-100.nip.io')
  assert.equal(logs.length, 0)
})

test('real IPC stops obsolete public failover after VPN starts, without waiting for another old public socket', async () => {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const start = source.indexOf('function publicDirectRequest(')
  const end = source.indexOf('/** Любой HTTP-статус', start)
  const callback = source.match(/ipcMain.handle\('tunnel-api-request', (async \(_, payload\) => \{[\s\S]*?\n\})\)/)[1]
  const refused = source.match(/function isTunnelApiRefused\(err\) \{[\s\S]*?\n\}/)[0]
  const pending = [], calls = [], logs = []
  const state = {
    ...failover, URL,
    UPDATE_HOST: '89-125-188-100.nip.io', SERVER_IP_FALLBACK: '89.125.188.100',
    hivePublicSlowUntil: 0,
    wgApplied: false, tunnelApiDown: false, tunnelApiRetryAfter: 0,
    captchaInProgress: false, apiQuietUntil: 0, wgRouteSettleUntil: 0,
    wgFullTunnelUpgradeInFlight: false, wgCredPhase: false,
    isOlcrtc2ApiPath: () => false, shouldLogTunnelApiFallback: () => true,
    sendLog: line => logs.push(line), ensurePublicApiBypass: async () => {}, sleep: async () => {},
    getPublicFailoverBases: () => ['https://89.125.188.100', 'http://87.58.213.193:9100', 'https://89.125.188.100:2083'],
    backendHttpRequest(opts) {
      calls.push(opts)
      if (opts.hostname === '10.66.66.1') return Promise.resolve({ status: 200, data: { source: 'tunnel' } })
      return new Promise((_, reject) => pending.push(reject))
    },
  }
  const request = vm.runInNewContext(`${refused}\n${source.slice(start, end)}\n(${callback})`, state)
  const result = request({}, { path: '/api/vpn/sync-state' })
  assert.equal(pending.length, 2, 'public hive and standby start in parallel before WG')
  state.wgApplied = true
  pending[0](Object.assign(new Error('connect EHOSTUNREACH'), { code: 'EHOSTUNREACH' }))
  let timer
  try {
    const response = await Promise.race([result, new Promise((_, reject) => { timer = setTimeout(() => reject(Error('obsolete standby still blocks healthy tunnel')), 150) })])
    assert.equal(response.data.source, 'tunnel')
  } finally {
    clearTimeout(timer)
    for (const reject of pending) reject(new Error('old public route closed'))
  }
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.filter(call => call.port === 2083).length, 0, 'do not continue public ports after the transport changed')
  assert.equal(logs.length, 0, 'cancelled old-route attempts are not final API failures')
})
