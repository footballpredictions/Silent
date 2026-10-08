const { test } = require('node:test')
const assert = require('node:assert/strict')

test('browser site allowlist never installs physical routes shared by applications', async () => {
  const wg = require('../src/main/vpn/wireguard')
  const saved = { ...wg }
  const modulePath = require.resolve('../src/main/apps/siteBypass')
  let added = []
  wg.capturePhysicalGateway = async () => ({ nextHop: '192.168.1.1', ifIndex: 5 })
  wg.addServerBypassRoutes = async targets => { added.push(...targets); return true }
  wg.removeHostBypassRoutes = async () => {}
  delete require.cache[modulePath]
  const sites = require(modulePath)
  try {
    await sites.applySiteBypass(['8.8.8.8'], null, { whitelist: true, browserOnly: true })
    assert.deepEqual(added, [], 'site mode must not bypass non-browser applications')
  } finally {
    await sites.clearSiteBypass()
    Object.assign(wg, saved)
    delete require.cache[modulePath]
  }
})

test('Windows site mode, deletion and disconnect update only browser policy', { skip: process.platform !== 'win32' }, async () => {
  const router = require('../src/main/vpn/browserRouter')
  const sites = require('../src/main/apps/siteBypass')
  await sites.applySiteBypass(['8.8.8.8'], null, { whitelist: true })
  assert.deepEqual(router.policySnapshot().targets, ['8.8.8.8/32'])
  assert.equal(router.policySnapshot().whitelist, true)
  await sites.applySiteBypass([], null, { whitelist: true })
  assert.deepEqual(router.policySnapshot().targets, [])
  assert.equal(router.policySnapshot().whitelist, true)
  await sites.applySiteBypass(['9.9.9.9'], null, { whitelist: false })
  assert.deepEqual(router.policySnapshot().targets, ['9.9.9.9/32'])
  assert.equal(router.policySnapshot().whitelist, false)
  const pending = sites.applySiteBypass(['1.0.0.1'], null, { whitelist: true })
  await sites.clearSiteBypass()
  assert.equal((await pending).cancelled, true)
  assert.deepEqual(router.policySnapshot().targets, [])
})

test('Windows app exclusions never install shared IP routes', { skip: process.platform !== 'win32' }, async () => {
  const router = require('../src/main/vpn/browserRouter')
  const { applyAppExclusionsForSession, clearActiveExcludedExePaths } = require('../src/main/apps/vpnAppExclusions')
  applyAppExclusionsForSession(['C:\\Games\\game.exe'])
  await router.updatePolicy({}) // wait for the app update in the same queue
  assert.deepEqual(router.policySnapshot().excluded, ['C:\\Games\\game.exe'])
  await clearActiveExcludedExePaths()
  assert.deepEqual(router.policySnapshot().excluded, [])
})
