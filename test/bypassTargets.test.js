/**
 * Peer/VK идут мимо WG. Публичный IP Улья — нет, если это не endpoint туннеля:
 * иначе админка/SSH с РФ бьются в заблокированный TCP, а Android держит Улей в туннеле.
 */
const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const {
  HIVE_PUBLIC_IP,
  collectTunnelBypassIps,
} = require('../src/main/vpn/bypassTargets')

describe('collectTunnelBypassIps', () => {
  it('on a cell does not bypass the hive public IP', () => {
    const ips = collectTunnelBypassIps({
      serverIp: '192.177.26.38',
      vkIps: ['87.240.137.130', '87.240.190.70'],
    })
    assert.ok(ips.includes('192.177.26.38'))
    assert.ok(ips.includes('87.240.137.130'))
    assert.equal(ips.includes(HIVE_PUBLIC_IP), false)
  })

  it('on the hive keeps the hive IP so WG UDP does not recurse', () => {
    const ips = collectTunnelBypassIps({
      serverIp: HIVE_PUBLIC_IP,
      vkIps: ['87.240.137.130'],
    })
    assert.ok(ips.includes(HIVE_PUBLIC_IP))
    assert.ok(ips.includes('87.240.137.130'))
  })
})

const {
  ADMIN_PANEL_URL,
  resolveAdminPanelUrl,
  isHivePublicUrl,
  isPaymentBrowserUrl,
} = require('../src/main/vpn/adminPanel')

describe('admin panel URL', () => {
  it('always opens public nip.io (VPN on cell, hive, or off)', () => {
    assert.equal(resolveAdminPanelUrl(false), ADMIN_PANEL_URL)
    assert.equal(resolveAdminPanelUrl(true, '87.58.213.193'), ADMIN_PANEL_URL)
    assert.equal(resolveAdminPanelUrl(true, '89.125.188.100'), ADMIN_PANEL_URL)
    assert.equal(ADMIN_PANEL_URL, 'https://89-125-188-100.nip.io/dashboard')
  })

  it('pins nip.io to tunnel gateway in hosts so hive-slot HTTPS stays in WG', () => {
    const { applyAdminNipPin } = require('../src/main/vpn/adminPanel')
    const pinned = applyAdminNipPin('127.0.0.1 localhost\n', { pin: true })
    assert.match(pinned, /10\.66\.66\.1\s+89-125-188-100\.nip\.io\s+# silent-vpn-admin-nip/)
    const cleared = applyAdminNipPin(pinned, { pin: false })
    assert.equal(cleared.includes('silent-vpn-admin-nip'), false)
    assert.match(cleared, /127\.0\.0\.1 localhost/)
  })

  it('strips hive from bypass on a cell so Chrome does not hit RF :443', () => {
    const { bypassWithoutHiveIfCell } = require('../src/main/vpn/adminPanel')
    const cell = bypassWithoutHiveIfCell(['87.58.213.193', '89.125.188.100'], '87.58.213.193')
    assert.deepEqual(cell, ['87.58.213.193'])
    const hive = bypassWithoutHiveIfCell(['89.125.188.100', '87.240.137.130'], '89.125.188.100')
    assert.deepEqual(hive, ['89.125.188.100', '87.240.137.130'])
  })

  it('does not treat admin nip.io as a payment bypass URL', () => {
    assert.equal(isHivePublicUrl(ADMIN_PANEL_URL), true)
    assert.equal(isPaymentBrowserUrl(ADMIN_PANEL_URL), false)
    assert.equal(isPaymentBrowserUrl('https://yoomoney.ru/checkout'), true)
  })
})
