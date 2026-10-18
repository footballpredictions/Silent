const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const vm = require('node:vm')
const russian = require('../src/main/apps/russianServices')
const bundled = require('../src/main/apps/russian-services-policy.json')
const sites = require('../src/main/apps/siteBypass')

function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-ru-'))
  return { dir, close: () => fs.rmSync(dir, { recursive: true, force: true }) }
}
test('RU mode defaults OFF; cached policy and independent flag survive restart', async () => {
  const f = fixture()
  try {
    const next = { ...bundled, revision: 'a'.repeat(64), direct_domains: ['ru', 'shop.com'] }
    const store = new russian.RussianServices(f.dir, async () => next)
    assert.equal(store.enabled(), false)
    assert.equal(store.deliveryStatus(), 'waiting')
    assert.equal(await store.refresh(), false)
    store.setEnabled(true)
    assert.equal(store.deliveryStatus(), 'waiting')
    assert.equal(await store.refresh(), true)
    store.markApplied()
    assert.equal(store.deliveryStatus(), 'received')
    assert.equal(store.snapshot().delivery, 'received')
    assert.deepEqual(
      (({ delivery, ...rest }) => rest)(store.snapshot()),
      { ...next, enabled: true },
    )
    store.setEnabled(false)
    assert.equal(store.deliveryStatus(), 'waiting')
    assert.deepEqual(
      (({ delivery, ...rest }) => rest)(new russian.RussianServices(f.dir).snapshot()),
      { ...next, enabled: false },
    )
  } finally { f.close() }
})
test('delivery becomes failed when every public endpoint rejects', async () => {
  const f = fixture()
  try {
    const store = new russian.RussianServices(f.dir, async () => { throw new Error('down') })
    store.setEnabled(true)
    assert.equal(await store.refresh(), false)
    assert.equal(store.deliveryStatus(), 'failed')
  } finally { f.close() }
})
test('invalid schema, suffixes and server errors retain the last validated cache', async () => {
  const f = fixture()
  try {
    for (const invalid of [{ ...bundled, schema_version: 2 }, { ...bundled, direct_domains: ['*.ru'] },
      { ...bundled, vpn_domains: ['a..ru'] }, { ...bundled, revision: 'bad' }]) assert.equal(russian.validPolicy(invalid), false)
    let calls = 0
    const store = new russian.RussianServices(f.dir, async () => { calls++; return { schema_version: 2 } })
    store.setEnabled(true)
    assert.equal(await store.refresh(), false)
    assert.equal(calls, 5)
    assert.equal(store.snapshot().revision, bundled.revision)
    fs.writeFileSync(store.file, JSON.stringify({ enabled: true, policy: { direct_domains: ['bad'] } }))
    assert.equal(new russian.RussianServices(f.dir).snapshot().revision, bundled.revision)
  } finally { f.close() }
})
test('production toggle IPC suppresses and restores manual routing without rewriting either list', async () => {
  const f = fixture()
  try {
    const appFile = path.join(f.dir, 'app-exclusions.json')
    const siteFile = sites.defaultSiteBypassPath(f.dir)
    fs.writeFileSync(appFile, JSON.stringify({ selectedIds: ['game'], exePaths: ['game.exe'], whitelist: false }))
    sites.saveSiteBypassState(siteFile, ['mail.ru'], false)
    sites.saveSiteBypassState(siteFile, ['example.com'], true)
    const before = [appFile, siteFile].map(file => fs.readFileSync(file, 'utf8'))
    const source = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
    const handler = source.match(/ipcMain.handle\('set-russian-services', (async \(_, enabled\) => \{[\s\S]*?\n\})\)/)[1]
    const prepare = source.match(/function prepareBrowserRoutingPolicy\(\) \{[\s\S]*?\n\}/)[0]
    const policies = []; const restored = []
    const context = vm.createContext({
      russianServices: russian, russianModeChanging: false,
      wgApplied: true, vpnBootstrapMode: false, sessionDnsOverride: null, lastVpnConnectConfig: null,
      app: { getPath: () => f.dir }, sendLog() {}, notifyRussianServices() {},
      require(name) {
        if (name === './vpn/browserRouter') return { updatePolicy: async policy => { policies.push(policy) } }
        if (name === './apps/appExclusionBypass') return { stopAppExclusionBypass: async () => {} }
        if (name === './apps/vpnAppExclusions') return {
          getActiveExcludedExePaths: () => ['game.exe'],
          applyAppExclusionsForSession: paths => restored.push(paths),
        }
        if (name === './apps/siteBypass') return { ...sites, clearSiteBypass: async () => {},
          applySiteBypassFromFile: async file => restored.push(sites.loadSiteBypassState(file).rules) }
        if (name === './apps/exclusionsState') return { defaultStatePath: () => appFile, loadExclusionsState: file => JSON.parse(fs.readFileSync(file)) }
        throw new Error(name)
      },
    })
    vm.runInContext(prepare, context)
    const toggle = vm.runInContext(`(${handler})`, context)
    assert.equal((await toggle({}, true)).ok, true)
    assert.equal(policies.at(-1).russian.enabled, true)
    assert.deepEqual(Array.from(policies.at(-1).excluded), [])
    assert.deepEqual(Array.from(policies.at(-1).targets), [])
    assert.equal((await toggle({}, false)).ok, true)
    assert.deepEqual(restored, [['game.exe'], ['example.com']])
    assert.deepEqual([appFile, siteFile].map(file => fs.readFileSync(file, 'utf8')), before)
  } finally { f.close() }
})
