const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { siteDirectTargets } = require('../src/main/apps/siteRoutingPolicy')

function contains(cidr, ip) {
  const number = value => value.split('.').reduce((n, octet) => n * 256 + Number(octet), 0)
  const [net, prefix] = cidr.split('/')
  const size = 2 ** (32 - Number(prefix))
  return Math.floor(number(net) / size) === Math.floor(number(ip) / size)
}

test('site allowlist sends other IPv4 addresses direct, preserving API and DNS', () => {
  const routes = siteDirectTargets(['8.8.8.8/32', '192.168.0.0/16'], true, ['1.1.1.1'])
  for (const ip of ['8.8.8.8', '192.168.55.4', '10.66.66.1', '1.1.1.1']) {
    assert.equal(routes.some(cidr => contains(cidr, ip)), false, ip)
  }
  for (const ip of ['0.0.0.0', '8.8.8.9', '192.169.1.1', '10.66.67.1', '255.255.255.255']) {
    assert.equal(routes.some(cidr => contains(cidr, ip)), true, ip)
  }
  assert.ok(routes.every(cidr => Number(cidr.split('/')[1]) >= 2))
})

test('overlapping CIDRs and full-range selection produce an exact complement', () => {
  assert.deepEqual(siteDirectTargets(['0.0.0.0/0'], true), [])
  const routes = siteDirectTargets(['128.0.0.0/1', '192.168.0.0/16'], true)
  assert.ok(routes.some(cidr => contains(cidr, '8.8.8.8')))
  assert.ok(!routes.some(cidr => contains(cidr, '128.0.0.1')))
})

test('empty allowlist uses direct routes, while old bypass mode stays unchanged', () => {
  const routes = siteDirectTargets([], true)
  assert.ok(routes.some(cidr => contains(cidr, '8.8.8.8')))
  assert.ok(!routes.some(cidr => contains(cidr, '10.66.66.1')))
  assert.deepEqual(siteDirectTargets(['8.8.8.8/32']), ['8.8.8.8/32'])
  assert.deepEqual(siteDirectTargets([], false), [])
})

test('mode survives reload; legacy files keep bypass mode and the same list', () => {
  const { loadSiteBypassState, saveSiteBypassState } = require('../src/main/apps/siteBypass')
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'silent-sites-'))
  const file = path.join(dir, 'sites.json')
  try {
    fs.writeFileSync(file, JSON.stringify({ version: 1, rules: ['8.8.8.8'] }))
    assert.equal(loadSiteBypassState(file).whitelist, false)
    saveSiteBypassState(file, ['8.8.8.8'], true)
    assert.equal(loadSiteBypassState(file).whitelist, true)
    saveSiteBypassState(file, ['8.8.8.8', '1.1.1.1'])
    assert.equal(loadSiteBypassState(file).whitelist, true)
    saveSiteBypassState(file, ['8.8.8.8', '1.1.1.1'], false)
    assert.equal(loadSiteBypassState(file).whitelist, false)
    assert.deepEqual(loadSiteBypassState(file).rules, ['8.8.8.8', '1.1.1.1'])
  } finally { fs.rmSync(dir, { recursive: true, force: true }) }
})

test('POSIX legacy route changes roll back and disconnect cancels queued changes', { skip: process.platform === 'win32' }, async () => {
  const wg = require('../src/main/vpn/wireguard')
  const saved = { ...wg }
  const bypassPath = require.resolve('../src/main/apps/siteBypass')
  const originalModule = require.cache[bypassPath]
  const direct = new Set()
  let failNextAdd = false
  const gateway = { nextHop: '192.168.1.1', ifIndex: 5 }
  wg.capturePhysicalGateway = async () => gateway
  wg.addServerBypassRoutes = async routes => {
    routes.forEach(route => direct.add(route))
    if (failNextAdd) { failNextAdd = false; return false }
    return true
  }
  wg.removeHostBypassRoutes = async (routes, send, epoch, options) => {
    assert.equal(options.physicalOnly, true)
    assert.equal(options.gateway, gateway)
    routes.forEach(route => direct.delete(route))
  }
  delete require.cache[bypassPath]
  const { applySiteBypass, clearSiteBypass } = require(bypassPath)
  try {
    await applySiteBypass(['8.8.8.8'], null, { whitelist: true, dnsServers: ['1.1.1.1'] })
    assert.ok([...direct].some(cidr => contains(cidr, '8.8.4.4')))
    assert.ok(![...direct].some(cidr => contains(cidr, '8.8.8.8')))
    await applySiteBypass(['8.8.8.8'], null, { whitelist: false })
    assert.deepEqual([...direct], ['8.8.8.8/32'])
    failNextAdd = true
    await assert.rejects(applySiteBypass(['9.9.9.9'], null, { whitelist: true }), /Не удалось/)
    assert.deepEqual([...direct], ['8.8.8.8/32'])
    await applySiteBypass([], null, { whitelist: true })
    assert.ok([...direct].some(cidr => contains(cidr, '8.8.8.8')))
    const pending = applySiteBypass(['1.0.0.1'], null, { whitelist: false })
    await clearSiteBypass()
    assert.equal((await pending).cancelled, true)
    assert.equal(direct.size, 0)
  } finally {
    await clearSiteBypass()
    Object.assign(wg, saved)
    if (originalModule) require.cache[bypassPath] = originalModule
    else delete require.cache[bypassPath]
  }
})
