const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const sites = require('../src/main/apps/siteBypass')

function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-site-lists-'))
  return { dir, file: sites.defaultSiteBypassPath(dir), close: () => fs.rmSync(dir, { recursive: true, force: true }) }
}

test('legacy site list migrates into its original mode, including an empty opposite mode', () => {
  const f = fixture()
  try {
    for (const whitelist of [false, true]) {
      fs.writeFileSync(f.file, JSON.stringify({ version: 1, whitelist, rules: ['2ip.io'] }))
      const legacy = sites.loadSiteBypassState(f.file)
      assert.deepEqual(legacy[whitelist ? 'whitelistRules' : 'blacklistRules'], ['2ip.io'])
      assert.deepEqual(sites.saveSiteBypassState(f.file, undefined, !whitelist).rules, [])
      assert.deepEqual(sites.saveSiteBypassState(f.file, undefined, whitelist).rules, ['2ip.io'])
    }
  } finally { f.close() }
})

test('disk saves, clearing and reload keep independent site lists and the legacy active mirror', () => {
  const f = fixture()
  try {
    sites.saveSiteBypassState(f.file, ['mail.ru'], false)
    sites.saveSiteBypassState(f.file, ['youtube.com', '2ip.io'], true)
    assert.deepEqual(sites.saveSiteBypassState(f.file, undefined, false).rules, ['mail.ru'])
    sites.saveSiteBypassState(f.file, [], false)
    assert.deepEqual(sites.saveSiteBypassState(f.file, undefined, true).rules, ['youtube.com', '2ip.io'])
    const reloaded = sites.loadSiteBypassState(f.file)
    assert.deepEqual(reloaded.blacklistRules, [])
    assert.deepEqual(reloaded.whitelistRules, ['youtube.com', '2ip.io'])
    assert.deepEqual(JSON.parse(fs.readFileSync(f.file)).rules, reloaded.rules)
  } finally { f.close() }
})

function renderer(storage, api) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/renderer/exclusionsStore.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText
  const exports = {}
  vm.runInNewContext(code, {
    exports, window: { electronAPI: api },
    localStorage: { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v)), removeItem: k => storage.delete(k) },
  })
  return exports
}
const plain = value => JSON.parse(JSON.stringify(value))

test('renderer and real main IPC switch only the selected saved list, including live updates and failed ACK', async () => {
  const f = fixture()
  const main = fs.readFileSync(require.resolve('../src/main/main'), 'utf8')
  const callback = main.match(/ipcMain.handle\('save-site-bypass', (async \(_, payload\) => \{[\s\S]*?\n\})\)/)[1]
  const applied = []
  let fail = false
  const handle = vm.runInNewContext(`(${callback})`, {
    app: { getPath: () => f.dir }, wgApplied: true, vpnBootstrapMode: false,
    sessionDnsOverride: null, lastVpnConnectConfig: null, sendLog() {},
    require: () => ({ ...sites, async applySiteBypass(rules, _, options) {
      applied.push({ rules, whitelist: options.whitelist })
      return { ok: !fail, targets: [], unresolved: [] }
    } }),
  })
  const api = { saveSiteBypass: payload => handle({}, payload) }
  const storage = new Map()
  let store = renderer(storage, api)
  try {
    await store.saveSiteBypassRules(['mail.ru'], false)
    await store.saveSitesMode(true)
    assert.deepEqual(plain(store.getSiteBypassRules()), [])
    await store.saveSiteBypassRules(['youtube.com', '2ip.io'])
    await store.saveSitesMode(false)
    assert.deepEqual(plain(store.getSiteBypassRules()), ['mail.ru'])
    assert.deepEqual(plain(applied.at(-1)), { rules: ['mail.ru'], whitelist: false })
    fail = true
    await assert.rejects(store.saveSitesMode(true), /Не удалось/)
    assert.equal(store.isSitesWhitelist(), false)
    assert.equal(sites.loadSiteBypassState(f.file).whitelist, false)
    fail = false
    await store.saveSiteBypassRules([])
    store = renderer(storage, api)
    await store.saveSitesMode(true)
    assert.deepEqual(plain(store.getSiteBypassRules()), ['youtube.com', '2ip.io'])
    assert.deepEqual(plain(store.getSiteBypassRules(false)), [])
    assert.deepEqual(sites.loadSiteBypassState(f.file).whitelistRules, ['youtube.com', '2ip.io'])
  } finally { f.close() }
})

test('renderer legacy cache migrates only to its old selected mode', () => {
  for (const whitelist of [false, true]) {
    const storage = new Map([['pc_site_bypass_rules', '["2ip.io"]'], ['pc_site_whitelist', whitelist ? '1' : '0']])
    const store = renderer(storage, {})
    assert.deepEqual(plain(store.getSiteBypassRules(whitelist)), ['2ip.io'])
    assert.deepEqual(plain(store.getSiteBypassRules(!whitelist)), [])
    store.hydrateSiteBypassState({ whitelist: !whitelist, rules: [], blacklistRules: [], whitelistRules: [] })
    assert.deepEqual(plain(store.getSiteBypassRules(whitelist)), [], 'explicitly cleared lists must not resurrect from legacy cache')
  }
})
