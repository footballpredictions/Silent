const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')

function fixture() {
  const state = { clock: 1000, starts: 0, stops: 0, routed: false, ready: true }
  const storage = new Map()
  const context = {
    URL,
    Date: { now: () => state.clock },
    crypto: { randomUUID: () => 'test-prelogin' },
    localStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v) },
    setInterval: fn => { state.tick = fn; return 1 }, clearInterval() {},
    window: { electronAPI: {
      vpnConnect: async config => { state.starts++; state.config = config; return {} },
      vpnDisconnect: async () => { state.stops++ },
      consumeFloodEscalate: async () => ({ escalate: false }),
    } },
  }
  const deps = {
    './vkConfig': { getBootstrapHash: () => 'test-vk-hash' },
    './debugLog': { pushLog() {} },
    './vkCredStore': {
      attachVkCredLaunchParams: c => c, escalateVkCredSession: () => false,
      getEffectiveVkCredStrategy: () => 'vkcalls', resetVkCredSessionEscalate() {},
      vkCredStrategyLabel: () => 'VK',
    },
    './sessionTrace': { SessionTrace: { enter() {}, mark() {} } },
    './hashChannelHelper': { applyBootstrapWorkerCount: c => c },
    './dnsPreset': { getDnsOverrideServers: () => null },
    './authStrings': { authStrings: {} },
    './vpnReady': { waitVpnReady: async () => state.ready },
    './tunnelApi': {
      enableTunnelApi() {}, clearTunnelApiBase() {},
      setBootstrapApiRouting: active => { state.routed = active },
    },
    './syncBootstrapData': { syncLoginDataViaTunnel: async () => ({}) },
    './themeStore': { getCachedTheme: () => null },
    './clientTheme': { standbyApiBasesFromTheme: () => [] },
  }
  function load(name) {
    const exports = {}
    const source = fs.readFileSync(require.resolve(`../src/renderer/${name}.ts`), 'utf8')
    vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
      target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS,
    } }).outputText, { ...context, exports, require: key => {
      assert.ok(deps[key], 'Unexpected dependency ' + key)
      return deps[key]
    } })
    return exports
  }
  deps['./bootstrapVpnConfig'] = load('bootstrapVpnConfig')
  return { state, api: load('bootstrapVpn') }
}

test('recovery builds its temporary VK config locally and routes API through the ready tunnel', async () => {
  const { state, api } = fixture()
  assert.equal(await api.ensureConnectBootstrapVpn(), true)
  assert.equal(api.isConnectBootstrapActive(), true)
  assert.equal(state.starts, 1)
  assert.equal(state.config.server_ip, '87.58.213.193')
  assert.equal(state.config.vk_hashes[0], 'test-vk-hash')
  assert.equal(state.routed, true)
  await api.disconnectBootstrapVpn()
  assert.equal(api.isConnectBootstrapActive(), false)
  assert.equal(state.routed, false)
  assert.equal(state.stops, 1)
})

test('an expired login timer does not prevent a later config recovery', async () => {
  const { state, api } = fixture()
  assert.equal(await api.ensureBootstrapVpn(), true)
  state.clock += 120001
  state.tick()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(api.isBootstrapExpired(), true)
  assert.equal(await api.ensureBootstrapVpn(), false)
  assert.equal(await api.ensureConnectBootstrapVpn(), true)
  assert.equal(state.starts, 2)
  await api.disconnectBootstrapVpn()
})

test('failed recovery stays owned until the caller cleans it up, then can retry', async () => {
  const { state, api } = fixture()
  state.ready = false
  assert.equal(await api.ensureConnectBootstrapVpn(), false)
  assert.equal(api.isConnectBootstrapActive(), true)
  await api.disconnectBootstrapVpn()
  assert.equal(api.isConnectBootstrapActive(), false)
  state.ready = true
  assert.equal(await api.ensureConnectBootstrapVpn(), true)
  await api.disconnectBootstrapVpn()
})

test('cancel while waiting for tunnel readiness invalidates the old recovery without reviving API routing', async () => {
  const { state, api } = fixture()
  let release
  state.starts = 0
  // Tunnel readiness is asynchronous on a restricted network.
  const originalReady = state.ready
  state.ready = new Promise(resolve => { release = resolve })
  const connecting = api.ensureConnectBootstrapVpn()
  while (!api.isBootstrapVpnActive()) await new Promise(resolve => setImmediate(resolve))
  await api.disconnectBootstrapVpn()
  release(originalReady)
  assert.equal(await connecting, false)
  assert.equal(api.isConnectBootstrapActive(), false)
  assert.equal(state.routed, false)
})
