const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')

const read = file => fs.readFileSync(path.join(__dirname, '..', file), 'utf8')
const renderer = read('src/renderer/pages/MainScreen.tsx')
const main = read('src/main/main.js')
const wireguard = read('src/main/vpn/wireguard.js')

test('logout keeps the profile open until the main VPN has stopped, including when the API fails', async () => {
  const events = []
  let finishStop
  const stopping = new Promise(resolve => { finishStop = resolve })
  const start = renderer.indexOf('  const handleLogout = ') + '  const handleLogout = '.length
  const end = renderer.indexOf('\n  const saveRename = ', start)
  const noop = () => {}
  const logout = vm.runInNewContext(ts.transpileModule(`(${renderer.slice(start, end).trim()})`, {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText, {
    window: { electronAPI: { vpnDisconnect: opts => { events.push(['stop', !!opts.slow]); return stopping } } },
    localStorage: { getItem: () => 'fixture-token' },
    DEVICE_FINGERPRINT: () => 'fixture-device',
    api: { post: async () => { events.push('api'); throw Error('offline') } },
    setLoggingOut: noop, setMenuOpen: noop, setMenuPage: noop, setDisconnecting: noop,
    setMainVpnSessionActive: noop, setConnected: noop, setConnecting: noop,
    resetVpnUi: () => events.push('switch off'),
    resetBootstrapRendererState: noop, stopOlcrtcHeartbeatLoop: noop,
    clearSnakeHold: noop, clearCachedVpnConfig: noop, clearCachedProfile: noop,
    clearSessionDeviceId: noop, clearSessionFingerprint: noop, resetConfigSyncOnLogout: noop,
    resetReachabilityReporter: noop, clearTokens: () => events.push('clear tokens'),
    onLogout: () => events.push('show login'), alert: message => events.push(message),
    connected: true, connecting: false, disconnecting: false,
    ...Object.fromEntries([
      'promoCheckVersionRef', 'profileFetchVersionRef', 'connectGenRef', 'disconnectTokenRef',
      'logoutBusyRef', 'connectLockRef', 'connectInFlightRef', 'onlineMarkedRef',
      'pendingConnectAfterSubscriptionRefreshRef',
    ].map(name => [name, { current: 0 }])),
    setTimeout: () => {},
  })
  const done = logout()
  assert.deepEqual(events, ['switch off', ['stop', true]])
  finishStop({ success: true })
  await done
  assert.deepEqual(events, ['switch off', ['stop', true], 'api', 'clear tokens', 'show login'])
})

test('installed-apps IPC starts the scan outside Electron main', async () => {
  const handler = main.match(/ipcMain\.handle\('list-installed-apps', ([\s\S]+?)\n\}\)/)[1]
  let scans = 0
  let finishScan
  const scan = new Promise(resolve => { finishScan = resolve })
  const list = vm.runInNewContext(`(${handler}\n})`, {
    require: () => ({
      listInstalledApps() { throw Error('synchronous scan blocked Electron main') },
      scanInstalledApps() { scans++; return scan },
    }),
    sendLog() {},
  })
  const pending = list()
  try {
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(scans, 1)
  } finally {
    finishScan([{ id: 'fixture' }])
  }
  assert.equal((await pending)[0].id, 'fixture')
})

test('the installer suppresses the system WireGuard window on fresh install', () => {
  const install = read('build/installer.nsh').split('\n').find(line => line.includes('msiexec /i'))
  assert.match(install, /\bDO_NOT_LAUNCH=1\b/)
})

test('confirmed disconnect waits for cleanup on every desktop platform and reports a remaining tunnel', async () => {
  const end = main.indexOf('async function fastDisconnectVpn')
  const start = main.lastIndexOf('async function cleanupVpnAsync', end)
  const handler = main.match(/ipcMain\.handle\('vpn-disconnect', ([\s\S]+?)\n\}\)/)[1]
  for (const platform of ['win32', 'darwin', 'linux']) {
    const calls = []
    let done
    const cleanup = new Promise(resolve => { done = resolve })
    const ctx = {
      process: { platform }, vpnConnectSeq: 2,
      cleanupVpn: () => { calls.push('cleanup'); return cleanup },
      waitForTunnelDown: async () => { calls.push('verify'); return false },
      sendLog() {},
    }
    const disconnect = vm.runInNewContext(`${main.slice(start, end)}\n(${handler}\n})`, ctx)
    const result = disconnect({}, { slow: true })
    assert.equal(ctx.vpnConnectSeq, 3)
    assert.deepEqual(calls, ['cleanup'], platform)
    done()
    assert.equal((await result).success, false)
    assert.deepEqual(calls, ['cleanup', 'verify'], platform)
  }
})

test('Windows repairs a stopped but registered wg-turn service and skips recovery on a clean start', async () => {
  const start = wireguard.indexOf('async function recoverIdleWindowsTunnel')
  const end = wireguard.indexOf('function buildWgConfigFromApi', start)
  const calls = []
  let serviceExists = false
  let restorePending = false
  const recover = vm.runInNewContext(`${wireguard.slice(start, end)}\nrecoverIdleWindowsTunnel`, {
    queryWgService: async () => ({ exists: serviceExists, running: false }),
    isTunnelUpAsync: async () => false,
    fs: { existsSync: () => restorePending }, IPV6_RESTORE_MARKER: 'fixture',
    forceStopWireGuard: async () => { calls.push('stop') },
    restoreIpv6Leak: async () => { calls.push('restore') },
  })
  await recover(false, 'fixture')
  assert.deepEqual(calls, [])
  serviceExists = true
  await recover(false, 'fixture')
  assert.deepEqual(calls, ['stop', 'restore'])
  serviceExists = false
  restorePending = true
  await recover(false, 'fixture')
  assert.deepEqual(calls, ['stop', 'restore', 'stop', 'restore'])
})
