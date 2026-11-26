const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

test('second instance during quit does not touch a destroyed BrowserWindow', () => {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const callback = source.match(/app\.on\('second-instance', (\(_, argv\) => \{[\s\S]*?\n  \})\)/)[1]
  let deepLinks = 0
  const handler = vm.runInNewContext(`(${callback})`, {
    mainWindow: {
      isDestroyed: () => true,
      isMinimized() { throw Error('Object has been destroyed') },
    },
    isQuitting: true,
    handleDeepLink() { deepLinks++ },
  })
  assert.doesNotThrow(() => handler({}, ['silentvpn://payment']))
  assert.equal(deepLinks, 0)
})

test('Windows window appears while firewall preparation is still pending', async () => {
  const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const start = source.indexOf('app.whenReady().then(') + 'app.whenReady().then('.length
  const end = source.indexOf('\n})\n\nlet vpnQuitFlushDone', start) + 2
  let ready, windows = 0
  const firewall = new Promise(resolve => { ready = resolve })
  const startup = vm.runInNewContext(`(${source.slice(start, end)})`, {
    app: { getPath: () => 'fixture', setAsDefaultProtocolClient() {}, isPackaged: true },
    process: { platform: 'win32', resourcesPath: 'fixture' },
    russianServices: { configure() {} }, startRussianPolicyRefresh() {}, softTamperHints() {},
    isDev: false, isDebugBuild: false, sendLog() {}, killOrphanWdtt() {}, vpnStartupRecovery: null,
    path: require('node:path'), fs: { existsSync: () => false },
    require: () => ({ ensureSilentVpnFirewallAllow: () => firewall, recoverIdleWindowsTunnel: async () => {} }),
    createWindow() { windows++ }, createTray() {}, warmVkExcludeIps() {},
  })
  const done = startup()
  try {
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(windows, 1, 'netsh firewall preparation must not delay the first window')
  } finally { ready(); await done }
})
