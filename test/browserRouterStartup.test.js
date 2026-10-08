const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const dns = require('node:dns').promises

test('real main startup prepares browser rules even when pre-VPN DNS never responds', async () => {
  const sites = require('../src/main/apps/siteBypass')
  const source = fs.readFileSync(require.resolve('../src/main/main.js'), 'utf8')
  const functionSource = source.match(/(?:async )?function prepareBrowserRoutingPolicy\(\) \{[\s\S]*?\n\}/)[0]
  const originalResolve = dns.resolve4, originalLookup = dns.lookup
  dns.resolve4 = () => new Promise(() => {})
  dns.lookup = () => new Promise(() => {})
  let timer
  try {
    const prepare = vm.runInNewContext(`(${functionSource})`, {
      app: { getPath: () => 'fixture' },
      require(name) {
        if (name === './apps/siteBypass') return { ...sites, loadSiteBypassState: () => ({ whitelist: true, rules: ['2ip.io', 'mail.ru', '8.8.8.8', '192.0.2.0/24'] }) }
        if (name === './apps/vpnAppExclusions') return { getActiveExcludedExePaths: () => ['game.exe'] }
        throw Error(name)
      },
    })
    const policy = await Promise.race([
      prepare(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(Error('site-router startup stuck waiting for DNS before VPN')), 150) }),
    ])
    assert.equal(policy.whitelist, true)
    assert.equal(policy.pendingDNS, true, 'startup must keep browsers in VPN until the first DNS snapshot')
    assert.deepEqual(Array.from(policy.domains), ['2ip.io', 'mail.ru'])
    assert.deepEqual(Array.from(policy.targets), ['8.8.8.8/32', '192.0.2.0/24'])
    assert.deepEqual(Array.from(policy.excluded), ['game.exe'])
  } finally {
    clearTimeout(timer)
    dns.resolve4 = originalResolve
    dns.lookup = originalLookup
  }
})

test('browser DNS snapshot cancels stalled queries within one budget and keeps IP rules', async () => {
  const originalResolver = dns.Resolver
  let queries = 0, cancelled = 0
  class StalledResolver {
    pending = []
    resolve4() { queries++; return new Promise((_, reject) => this.pending.push(reject)) }
    cancel() { cancelled++; for (const reject of this.pending.splice(0)) reject(Error('cancelled')) }
  }
  dns.Resolver = StalledResolver
  try {
    const sites = require('../src/main/apps/siteBypass')
    const started = Date.now()
    const result = await sites.resolveBrowserRulesToTargets(['8.8.8.8', ...Array.from({ length: 40 }, (_, i) => `stalled${i}.example`)], { timeoutMs: 35 })
    assert.ok(Date.now() - started < 500, 'a stalled imported list must have one total deadline')
    assert.ok(queries <= 8, 'do not flood DNS with the full imported list')
    assert.ok(cancelled > 0)
    assert.deepEqual(result.targets, ['8.8.8.8/32'])
    assert.equal(result.unresolved.length, 40)
  } finally { dns.Resolver = originalResolver }
})

test('browser snapshots preserve remaining cached sites on DNS failure and drop deleted rules', async () => {
  const originalResolver = dns.Resolver
  let offline = false
  dns.Resolver = class {
    async resolve4(host) {
      if (offline) throw Error('DNS unavailable')
      return [host === 'cached.example' ? '192.0.2.1' : '192.0.2.2']
    }
    cancel() {}
  }
  try {
    const sites = require('../src/main/apps/siteBypass')
    await sites.resolveBrowserRulesToTargets(['cached.example', 'deleted.example'])
    offline = true
    const result = await sites.resolveBrowserRulesToTargets(['cached.example', 'new.example'])
    assert.deepEqual(result.targets, ['192.0.2.1/32'])
    assert.deepEqual(result.unresolved, ['new.example'])
    assert.deepEqual((await sites.resolveBrowserRulesToTargets([])).targets, [])
  } finally { dns.Resolver = originalResolver }
})

test('live domain rules use VPN DNS rather than the pre-connect system resolver', async () => {
  const originalResolver = dns.Resolver
  let selectedServers
  dns.Resolver = class {
    setServers(servers) { selectedServers = servers }
    async resolve4() {
      if (!selectedServers) throw Error('old LAN DNS unreachable through VPN')
      return ['188.40.167.81']
    }
    cancel() {}
  }
  const sites = require('../src/main/apps/siteBypass')
  const router = require('../src/main/vpn/browserRouter')
  try {
    const result = await sites.applySiteBypass(['2ip.io'], null, { whitelist: true, browserOnly: true, dnsServers: ['1.1.1.1', '1.0.0.1'] })
    assert.equal(result.ok, true)
    assert.deepEqual(router.policySnapshot().targets, ['188.40.167.81/32'], 'selected Chrome site must have a VPN IP rule even with unusable system DNS')
    assert.deepEqual(selectedServers, ['1.1.1.1', '1.0.0.1'])
  } finally {
    await sites.clearSiteBypass()
    dns.Resolver = originalResolver
  }
})

test('site router logs preserve policy acknowledgements and distinguish recoverable Wintun rename', () => {
  const source = fs.readFileSync(require.resolve('../src/main/main.js'), 'utf8')
  const functionSource = source.match(/function sendLog\(line\) \{[\s\S]*?\n\}/)[0]
  const entries = [], mirrored = []
  const send = vm.runInNewContext(`(${functionSource})`, {
    process: { platform: 'win32' },
    noteVkFloodFromLog: () => {},
    mirrorMainLog: line => mirrored.push(line),
    sendWdttLog: entry => entries.push(entry),
    parseLibclientLine: require('../src/main/libclientLogParser').parseLibclientLine,
  })
  send('[Sites] Правила применены: БС, доменов=1, IP=1')
  send('[Sites] 2026/10/08 Failed to set foreign adapter name to "wg-turn 43": Элемент не найден. (Code 0x00000490)')
  send('[Sites] site-router: Error creating interface: access denied')
  assert.equal(entries.length, 3, 'successful policy ACK must be visible too')
  assert.equal(entries[0].isError, false)
  assert.equal(entries[1].isError, false, 'recoverable foreign adapter rename must not be shown as fatal VPN failure')
  assert.equal(entries[2].isError, true, 'actual router failures must remain visible')
  assert.equal(mirrored.length, 3)
})
