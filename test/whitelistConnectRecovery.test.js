const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

function fixture({ cached = null, denied = false } = {}) {
  const source = fs.readFileSync(require.resolve('../src/renderer/pages/MainScreen.tsx'), 'utf8').replace(/\r\n/g, '\n')
  const start = source.indexOf('  const handleToggle = async () => {')
  const end = source.indexOf('\n  const runMainVpnConnect =', start)
  const config = { wg_private_key: 'test-key', server_public_key: 'test-peer', vk_hashes: ['test-hash'], selected_server: 'server2', server_ip: '87.58.213.193' }
  const state = { alerts: [], launches: [], events: [], active: false, held: false, cached }
  const context = { console, window: { electronAPI: { vpnIsReady: async () => ({ ready: false }) } },
    connected: false, connecting: false, disconnecting: false,
    isOlcrtcBypass: () => false, getCachedProfile: () => null,
    fetchProfile: async () => null, notifyDisconnect: async () => {}, DEVICE_FINGERPRINT: () => 'test-fp',
    getCachedVpnConfig: () => state.cached, cachedConfigMatchesPreferred: () => true,
    getPreferredServer: () => 'server2', saveSessionDeviceId() {},
    cacheVpnConfig: c => { state.cached = c }, hydrateFromVpnConfig() {},
    isBootstrapVpnActive: () => state.active,
    isConnectBootstrapActive: () => state.held,
    disconnectBootstrapVpn: async () => { state.active = false; state.held = false; state.events.push('stop-bootstrap') },
    ensureConnectBootstrapVpn: async () => { state.held = true; state.active = true; state.events.push('start-bootstrap'); return true },
    runMainVpnConnect: async c => { state.launches.push(c); state.events.push('main-connect') },

    alert: m => state.alerts.push(m), pushLog() {}, SessionTrace: { enter() {} },
  }
  for (const name of ['connectLockRef','connectInFlightRef','userWantsVpnRef','onlineMarkedRef','pendingConnectAfterSubscriptionRefreshRef']) context[name] = { current: false }
  for (const name of ['connectGenRef','disconnectTokenRef','tunnelUpAtRef']) context[name] = { current: 0 }
  for (const name of ['setMainVpnSessionActive','setActiveWorkers','clearVpnLogs','clearLogs','startSnakeHold','clearSnakeHold','setVpnReady','setMenuOpen','setMenuPage','setConnected','setConnecting','setDisconnecting','resetVpnUi']) context[name] = () => {}
  const apiCall = async kind => {
    state.events.push(`${state.active ? 'tunnel' : 'public'}-${kind}`)
    if (denied) throw { response: { status: typeof denied === 'number' ? denied : 402, data: { detail: 'Access denied' } } }
    if (!state.active) throw Object.assign(new Error('connect ETIMEDOUT'), { code: 'ETIMEDOUT' })
    return { data: config }
  }
  const module = { exports: {} }
  const fetchContext = { exports: module.exports, require(name) {
    if (name === './api') return { default: { post: () => apiCall('register'), get: () => apiCall('config') }, formatApiError: e => e.message }
    if (name === './debugLog') return { pushLog() {} }
    if (name === './bypassStore') return { getPreferredServer: context.getPreferredServer }
    throw Error('Unexpected dependency ' + name)
  } }
  const fetchSource = fs.readFileSync(require.resolve('../src/renderer/vpnConfigFetch.ts'), 'utf8')
  vm.runInNewContext(ts.transpileModule(fetchSource, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS } }).outputText, fetchContext)
  context.fetchVpnConfigWithKeys = module.exports.fetchVpnConfigWithKeys
  vm.runInNewContext(ts.transpileModule(source.slice(start,end), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText+'\nglobalThis.toggle = handleToggle',context)
  return { state, context, toggle: () => context.toggle() }
}

test('PC connects on a whitelist-only network without first visiting unrestricted Wi-Fi', async () => {
  const f = fixture()
  await f.toggle()
  await new Promise(r => setImmediate(r))
  assert.deepEqual(f.state.alerts, [], 'must recover config instead of asking the user to log out and set hash')
  assert.equal(f.state.launches.length, 1, 'main VPN must start after fetching config over temporary VK tunnel')
  assert.deepEqual(f.state.events, ['public-register', 'public-config', 'start-bootstrap', 'tunnel-register', 'stop-bootstrap', 'main-connect'])
})

test('a complete cached config starts offline without another bootstrap', async () => {
  const f = fixture({ cached: { wg_private_key: 'test-key', server_public_key: 'test-peer', vk_hashes: ['test-hash'] } })
  await f.toggle()
  assert.equal(f.state.launches.length, 1)
  assert.deepEqual(f.state.events, ['main-connect'])
})

test('subscription rejection cannot start recovery or bypass access checks', async () => {
  const f = fixture({ denied: true })
  await f.toggle()
  assert.equal(f.state.launches.length, 0)
  assert.deepEqual(f.state.events, ['public-register'])
})


test('cancelling while the temporary tunnel starts prevents a late main VPN launch', async () => {
  const f = fixture()
  let release
  f.context.ensureConnectBootstrapVpn = async () => {
    f.state.held = true
    f.state.events.push('start-bootstrap')
    await new Promise(r => { release = r })
    return false
  }
  const first = f.toggle()
  while (!release) await new Promise(r => setImmediate(r))
  f.context.connecting = true
  await f.toggle()
  release()
  await first
  assert.equal(f.state.held, false)
  assert.equal(f.state.launches.length, 0)
  assert.equal(f.state.events.filter(e => e === 'stop-bootstrap').length, 1)
})

test('failed temporary tunnel is cleaned up and allows another attempt', async () => {
  const f = fixture()
  f.context.ensureConnectBootstrapVpn = async () => { f.state.held = true; return false }
  await f.toggle()
  assert.equal(f.state.held, false)
  assert.equal(f.context.connectLockRef.current, false)
  assert.equal(f.state.launches.length, 0)
  assert.equal(f.state.events.filter(e => e === 'stop-bootstrap').length, 1)
})

test('access denied through recovered tunnel stops it without launching main VPN', async () => {
  const f = fixture()
  const original = f.context.fetchVpnConfigWithKeys
  f.context.fetchVpnConfigWithKeys = async fp => {
    if (f.state.active) throw { response: { status: 403, data: { detail: 'Access denied' } } }
    return original(fp)
  }
  await f.toggle()
  assert.equal(f.state.active, false)
  assert.equal(f.state.held, false)
  assert.equal(f.state.launches.length, 0)
})

test('a later cancellation cannot stop the new connection after a stale config reply', async () => {
  const f = fixture()
  const original = f.context.fetchVpnConfigWithKeys
  let release
  f.context.fetchVpnConfigWithKeys = async fp => {
    if (f.state.active) await new Promise(r => { release = r })
    return original(fp)
  }
  const first = f.toggle()
  while (!release) await new Promise(r => setImmediate(r))
  f.context.connecting = true
  await f.toggle()
  // A new user-owned main connection has started while the old API request completes.
  f.context.connectGenRef.current++
  f.state.events.length = 0
  release()
  await first
  assert.equal(f.state.launches.length, 0)
  assert.equal(f.state.events.filter(e => e === 'stop-bootstrap').length, 0)
})


test('actual config loader preserves HTTP 403 and does not retry it as a network failure', async () => {
  const f = fixture({ denied: 403 })
  await f.toggle()
  assert.deepEqual(f.state.events, ['public-register'])
  assert.equal(f.state.launches.length, 0)
  assert.equal(f.state.held, false)
})
