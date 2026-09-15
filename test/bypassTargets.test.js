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
