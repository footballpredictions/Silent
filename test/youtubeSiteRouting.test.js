const { test } = require('node:test')
const assert = require('node:assert/strict')
const dns = require('node:dns').promises
const sites = require('../src/main/apps/siteBypass')
const router = require('../src/main/vpn/browserRouter')

test('YouTube live browser policy includes video and image hosts in both modes and removes them with the rule', async () => {
  const original = dns.Resolver
  const addresses = { 'youtube.com': '192.0.2.1', 'i.ytimg.com': '192.0.2.2', 'yt3.ggpht.com': '192.0.2.3' }
  dns.Resolver = class {
    async resolve4(host) { return addresses[host] ? [addresses[host]] : [] }
    cancel() {}
  }
  try {
    for (const whitelist of [true, false]) {
      await sites.applySiteBypass(['youtube.com'], null, { whitelist, browserOnly: true })
      const policy = router.policySnapshot()
      assert.equal(policy.whitelist, whitelist)
      for (const domain of ['youtube.com', 'googlevideo.com', 'ytimg.com', 'ggpht.com']) {
        assert.ok(policy.domains.includes(domain), `missing YouTube resource domain ${domain}`)
      }
      for (const ip of Object.values(addresses)) assert.ok(policy.targets.includes(`${ip}/32`), `missing cached resource ${ip}`)
      assert.equal(policy.pendingDNS, false, 'CDN roots without A records must not keep all browser traffic in VPN')
    }
    await sites.applySiteBypass(['unrelated.example'], null, { whitelist: true, browserOnly: true })
    assert.deepEqual(router.policySnapshot().domains, ['unrelated.example'])
    assert.equal(router.policySnapshot().targets.length, 0, 'removed YouTube CDN snapshots must not survive')
    const exact = sites.initialBrowserPolicy(['notyoutube.com', 'youtube.com.other.example', '192.0.2.0/24'], true)
    assert.deepEqual(exact.domains, ['notyoutube.com', 'youtube.com.other.example'])
    assert.deepEqual(sites.parseRules('youtube.com'), ['youtube.com'], 'saved/displayed rules stay as entered')
    assert.ok(sites.initialBrowserPolicy(['www.youtube.com'], true).domains.includes('googlevideo.com'))
  } finally {
    await sites.clearSiteBypass()
    dns.Resolver = original
  }
})
