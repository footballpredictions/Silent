const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const {
  cellIpsFromUrls,
  pickBootstrapOverlay,
  isHiveBootstrapIp,
} = require('../src/main/vpn/bootstrapOverlay')

describe('pickBootstrapOverlay', () => {
  it('temp vpn for mail uses a live cell not flapping hive udp', () => {
    const got = pickBootstrapOverlay({
      hiveIp: '89.125.188.100',
      hivePort: 56000,
      cellIps: ['87.58.213.193', '78.17.74.27'],
    })
    assert.equal(got.ip, '87.58.213.193')
    assert.equal(got.port, 56000)
    assert.equal(got.isHive, false)
  })

  it('without cells overlay stays on hive', () => {
    const got = pickBootstrapOverlay({
      hiveIp: '89.125.188.100',
      hivePort: 56000,
      cellIps: [],
    })
    assert.equal(got.ip, '89.125.188.100')
    assert.equal(got.isHive, true)
  })
})

describe('cellIpsFromUrls', () => {
  it('yields cell ips and skips hive and ai cell', () => {
    const ips = cellIpsFromUrls([
      'http://87.58.213.193:9100',
      'https://89-125-188-100.nip.io:2083',
      'https://89.125.188.100:2083',
      'http://78.17.74.27:9100',
      'http://192.177.26.38:9100',
    ])
    assert.deepEqual(ips, ['87.58.213.193', '78.17.74.27'])
  })
})

describe('isHiveBootstrapIp', () => {
  it('full tunnel when overlay is a cell', () => {
    assert.equal(isHiveBootstrapIp('87.58.213.193'), false)
    assert.equal(isHiveBootstrapIp('89.125.188.100'), true)
  })
})
