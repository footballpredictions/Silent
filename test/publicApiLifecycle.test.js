const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const failover = require('../src/main/vpn/apiFailover')

function harness(backend, bases = ['https://89.125.188.100', 'http://87.58.213.193:9100', 'https://89.125.188.100:2083']) {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const start = source.indexOf('function publicDirectRequest(')
  const end = source.indexOf('\nfunction tunnelHttpRequest(', start)
  const calls = [], logs = [], diagnostics = []
  const state = {
    ...failover, URL, AbortController, setInterval, clearInterval,
    UPDATE_HOST: '89-125-188-100.nip.io', SERVER_IP_FALLBACK: '89.125.188.100',
    hivePublicSlowUntil: 0,
    publicApiPreferredBase: '',
    getPublicFailoverBases: () => bases,
    sendLog: line => logs.push(line),
    mirrorMainLog: line => diagnostics.push(line),
    backendHttpRequest(opts) { calls.push(opts); return backend(opts) },
  }
  const request = vm.runInNewContext(`(${source.slice(start, end)})`, state)
  return { request, calls, logs, diagnostics }
}

test('successful public read stops the losing chain before it opens another port or reports stale errors', async () => {
  let failHive
  const { request, calls, logs } = harness(opts => opts.protocol === 'http'
    ? Promise.resolve({ status: 200, data: 'cell' })
    : new Promise((_, reject) => { failHive = reject }))
  assert.equal((await request({ path: '/api/users/me' })).data, 'cell')
  failHive(new Error('API timeout'))
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls.length, 2, 'a completed request must not start a stale :2083 connection')
  assert.equal(logs.length, 0)
})

test('a public mutation is sent once even if its response is lost', async () => {
  const { request, calls } = harness(async () => { throw new Error('socket hang up') })
  await assert.rejects(request({ method: 'POST', path: '/api/payments/init', body: { plan: 'fixture' } }), /socket hang up/)
  assert.equal(calls.length, 1, 'do not race or replay an already dispatched POST across hive and cells')
})

test('public reads still fail over when the first route fails', async () => {
  const { request } = harness(async opts => {
    if (opts.protocol === 'https') throw new Error('EHOSTUNREACH')
    return { status: 200, data: 'cell' }
  })
  assert.equal((await request({ path: '/api/users/me' })).data, 'cell')
})

test('mutations use the last responding API route instead of returning to an unreachable hive', async () => {
  const { request, calls } = harness(async opts => {
    if (opts.protocol === 'https') throw new Error('EHOSTUNREACH')
    return { status: 200, data: 'cell' }
  })
  await request({ path: '/api/users/me' })
  calls.length = 0
  assert.equal((await request({ method: 'POST', path: '/api/vpn/connect' })).data, 'cell')
  assert.equal(calls.length, 1)
  assert.equal(calls[0].hostname, '87.58.213.193')
})

test('a mutation may fail over only when the transport proves nothing was dispatched', async () => {
  const { request, calls } = harness(async opts => {
    if (opts.protocol === 'https') throw Object.assign(new Error('ECONNREFUSED'), { requestDispatched: false })
    return { status: 200, data: 'cell' }
  })
  assert.equal((await request({ method: 'POST', path: '/api/auth/login' })).data, 'cell')
  assert.equal(calls.length, 2)
})

test('a hive 503 does not beat a healthy cell response', async () => {
  const { request } = harness(async opts => ({ status: opts.protocol === 'https' ? 503 : 200, data: opts.protocol }))
  assert.equal((await request({ path: '/api/users/me' })).status, 200)
})

test('a public read aborts as soon as VPN is ready, without waiting for blocked public socket timeouts', async () => {
  let ready = false, timer
  const pending = []
  const { request, calls, logs } = harness(opts => new Promise((_, reject) => {
    pending.push(reject)
    opts.signal.addEventListener('abort', () => reject(new Error('Public API request superseded by VPN')), { once: true })
  }))
  const result = request({ path: '/api/vpn/sync-state', shouldSwitchToTunnel: () => ready })
  ready = true
  try {
    await Promise.race([
      assert.rejects(result, /superseded by VPN/),
      new Promise((_, reject) => { timer = setTimeout(() => reject(Error('healthy VPN still waits for blocked public sockets')), 300) }),
    ])
  } finally {
    clearTimeout(timer)
    for (const reject of pending) reject(new Error('Public API request superseded by VPN'))
  }
  assert.equal(calls.length, 2)
  assert.equal(logs.length, 0)
})

test('a successful API read keeps intermediate public timeouts in diagnostics instead of displaying a VPN failure', async () => {
  const { request, logs, diagnostics } = harness(async opts => {
    if (opts.hostname === '87.58.213.193') throw Error('Public API timeout')
    return { status: 200, data: 'second cell' }
  }, ['http://87.58.213.193:9100', 'http://78.17.74.27:9100'])
  assert.equal((await request({ path: '/api/users/me' })).data, 'second cell')
  assert.equal(logs.length, 0, 'an API request that succeeded must not leave an intermediate error in the UI')
  assert.equal(diagnostics.length, 1, 'the failed hop remains available for network diagnosis')
  assert.match(diagnostics[0], /87\.58\.213\.193.*timeout/)
})
