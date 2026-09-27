const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const {
  publicFailoverBases,
  publicFailoverAttemptTimeoutMs,
  publicBasesSkippingHive,
  shouldLogPublicHopFail,
  rewriteStoredPublicBase,
} = require('../src/main/vpn/apiFailover')

describe('publicFailoverBases', () => {
  it('tries hive HTTPS first, then cell 1, then the next cell', () => {
    const bases = publicFailoverBases({
      hiveHost: '89-125-188-100.nip.io',
      hiveIp: '89.125.188.100',
      baked: ['http://87.58.213.193:9100', 'http://78.17.74.27:9100'],
    })
    assert.equal(bases[0], 'https://89.125.188.100')
    assert.equal(bases[1], 'http://87.58.213.193:9100')
    assert.equal(bases[2], 'http://78.17.74.27:9100')
    assert.equal(bases[3], 'https://89-125-188-100.nip.io')
  })

  it('keeps hive alt ports after cells so a dead :2083 cannot stall login', () => {
    const bases = publicFailoverBases({
      hiveHost: '89-125-188-100.nip.io',
      hiveIp: '89.125.188.100',
      baked: ['http://87.58.213.193:9100'],
      standby: ['https://89-125-188-100.nip.io:2083', 'http://78.17.74.27:9100'],
    })
    assert.equal(bases[0], 'https://89.125.188.100')
    assert.equal(bases[1], 'http://87.58.213.193:9100')
    assert.equal(bases[2], 'http://78.17.74.27:9100')
    assert.equal(bases[3], 'https://89-125-188-100.nip.io')
    assert.equal(bases[4], 'https://89-125-188-100.nip.io:2083')
  })

  it('drops retired hive IP and rewrites stored prefs to current nip', () => {
    assert.equal(
      rewriteStoredPublicBase('https://132.243.234.162'),
      'https://89-125-188-100.nip.io',
    )
    const bases = publicFailoverBases({
      hiveHost: '89-125-188-100.nip.io',
      hiveIp: '89.125.188.100',
      baked: ['http://87.58.213.193:9100', 'https://132.243.234.162'],
      stored: 'https://132.243.234.162',
    })
    assert.equal(bases[0], 'https://89.125.188.100')
    assert.equal(bases[1], 'http://87.58.213.193:9100')
    assert.ok(!bases.some((u) => u.includes('132.243')))
  })
})

describe('publicBasesSkippingHive', () => {
  it('drops the hive IP and nip.io so a live tunnel does not wait on :443', () => {
    const hive = { hiveHost: '89-125-188-100.nip.io', hiveIp: '89.125.188.100' }
    const bases = publicFailoverBases({
      ...hive,
      baked: ['http://87.58.213.193:9100', 'http://78.17.74.27:9100'],
      standby: ['https://89-125-188-100.nip.io:2083'],
    })
    const left = publicBasesSkippingHive(bases, hive)
    assert.deepEqual(left, ['http://87.58.213.193:9100', 'http://78.17.74.27:9100'])
  })
})

describe('shouldLogPublicHopFail', () => {
  const hive = { hiveHost: '89-125-188-100.nip.io', hiveIp: '89.125.188.100' }

  it('hides a hive timeout when a cell is still to be tried', () => {
    assert.equal(shouldLogPublicHopFail('https://89.125.188.100', 'API timeout', hive, true), false)
    assert.equal(shouldLogPublicHopFail('http://87.58.213.193:9100', 'API timeout', hive, true), true)
    assert.equal(shouldLogPublicHopFail('https://89.125.188.100', 'API timeout', hive, false), true)
  })
})

describe('publicFailoverAttemptTimeoutMs', () => {
  it('gives the hive long enough to answer before the cell proxy', () => {
    const hiveMs = publicFailoverAttemptTimeoutMs('https://89-125-188-100.nip.io', 20000, {
      hiveHost: '89-125-188-100.nip.io',
      hiveIp: '89.125.188.100',
    })
    const cellMs = publicFailoverAttemptTimeoutMs('http://87.58.213.193:9100', 20000, {
      hiveHost: '89-125-188-100.nip.io',
      hiveIp: '89.125.188.100',
    })
    assert.equal(hiveMs, 8000)
    assert.equal(cellMs, 8000)
  })
})
