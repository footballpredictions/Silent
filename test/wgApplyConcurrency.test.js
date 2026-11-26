const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

function fixture() {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const start = source.indexOf('  const tryApplyWg = async (') + '  const tryApplyWg = '.length
  const end = source.indexOf('\n  const applyFromFile = ', start)
  let release, installs = 0, policyCalls = 0
  const policy = new Promise(resolve => { release = resolve })
  const noop = () => {}
  const state = {
    vpnConnectSeq: 1, switching: false, wgApplied: false, wgFailed: false,
    wgInstallInFlight: false, wgAttempted: false, vpnSessionActive: true,
    vpnBootstrapMode: false, wgCredPhase: false, config: {},
    sessionDnsOverride: '', confPath: 'fixture', excludeIPs: [], isDev: false, __dirname: 'fixture',
    resolveWgMtu: () => 1200, normalizeWgConfText: x => x, sendLog: noop,
    waitForWdttProxy: async () => true, fs: { writeFileSync: noop },
    isServiceRunningAsync: async () => !!state.serviceRunning, process: { platform: 'win32' },
    prepareBrowserRoutingPolicy: () => ({}),
    applyWireGuardConfig: async () => { installs++; return state.installOk ?? true },
    isProcessElevated: () => true, setTimeout: () => 0, clearTimeout: noop,
    require: name => {
      if (name === './vpn/browserRouter') return { updatePolicy: async () => {
        policyCalls++
        await policy
        if (state.rejectPolicy) throw Error('policy rejected')
      } }
      if (name === './apps/vpnAppExclusions') return { refreshAppExclusionBypassAfterTunnel: async () => {} }
      if (name === './apps/siteBypass') return { applySiteBypassFromFile: async () => {}, defaultSiteBypassPath: () => 'fixture' }
      throw Error(name)
    },
    clearWgRetries: noop, addServerBypassRoutes: async () => {}, ensureNipIoBypassRoutes: async () => {},
    syncAdminNipHosts: async () => {}, peerIsHive: () => false, ADMIN_HIVE_IP: '',
    scheduleBypassRefresh: noop, app: { getPath: () => 'fixture' },
    scheduleTunnelReadyPoll: noop, ensureVpnReadyEvent: noop,
    failWireGuard: message => { state.wgFailed = true; state.failure = message },
  }
  const apply = vm.runInNewContext(`(${source.slice(start, end).trim()})`, state)
  return { state, release, apply: () => apply('[Interface]\nAddress = 10.0.0.2/32\n', 'wdtt-file'), installs: () => installs, policyCalls: () => policyCalls }
}

test('GETCONF poll cannot reinstall a healthy adapter while post-install policy is pending', async () => {
  const f = fixture()
  const first = f.apply()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(f.policyCalls(), 1, 'the first adapter is installed, but policy ACK is delayed')
  const second = f.apply()
  await new Promise(resolve => setImmediate(resolve))
  try {
    assert.equal(f.installs(), 1, 'a poll must not tear down and create the same adapter twice')
  } finally { f.release(); await Promise.all([first, second]) }
})

test('old post-install completion cannot resurrect a disconnected session or release a new install guard', async () => {
  const f = fixture()
  const first = f.apply()
  await new Promise(resolve => setImmediate(resolve))
  f.state.vpnConnectSeq++
  f.state.vpnSessionActive = false
  f.state.wgInstallInFlight = true
  f.release()
  assert.equal(await first, false)
  assert.equal(f.state.wgApplied, false)
  assert.equal(f.state.wgInstallInFlight, true, 'a previous connection must not release a later connection guard')
})

test('policy setup failure reports a failed install and releases its guard without an unhandled rejection', async () => {
  const f = fixture()
  f.state.rejectPolicy = true
  const first = f.apply()
  f.release()
  assert.equal(await first, false)
  assert.equal(f.state.wgApplied, false)
  assert.equal(f.state.wgInstallInFlight, false)
  assert.match(f.state.failure, /policy rejected/)
})

test('an explicit install failure never reports a leftover Windows service as a ready VPN', async () => {
  const f = fixture()
  f.state.serviceRunning = true
  f.state.installOk = false
  f.release()
  assert.equal(await f.apply(), false)
  assert.equal(f.policyCalls(), 0)
  assert.equal(f.state.wgApplied, false)
})
