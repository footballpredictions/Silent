const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const {
  publicFailoverBases,
  publicFailoverAttemptTimeoutMs,
} = require('../src/main/vpn/apiFailover')

describe('publicFailoverBases', () => {
  it('tries cells first, then hive HTTPS', () => {
    const bases = publicFailoverBases({
      hiveHost: '132-243-234-162.nip.io',
      hiveIp: '132.243.234.162',
      baked: ['http://87.58.213.193:9100', 'http://78.17.74.27:9100'],
    })
    assert.equal(bases[0], 'http://87.58.213.193:9100')
    assert.equal(bases[1], 'http://78.17.74.27:9100')
    assert.equal(bases[2], 'https://132-243-234-162.nip.io')
    assert.equal(bases[3], 'https://132.243.234.162')
  })

  it('keeps cells ahead of hive alt ports so a dead :2083 cannot stall login', () => {
    const bases = publicFailoverBases({
      hiveHost: '132-243-234-162.nip.io',
      hiveIp: '132.243.234.162',
      baked: ['http://87.58.213.193:9100'],
      standby: ['https://132-243-234-162.nip.io:2083', 'http://78.17.74.27:9100'],
    })
    assert.equal(bases[0], 'http://87.58.213.193:9100')
    assert.equal(bases[1], 'http://78.17.74.27:9100')
    assert.equal(bases[2], 'https://132-243-234-162.nip.io')
    assert.equal(bases[3], 'https://132.243.234.162')
    assert.equal(bases[4], 'https://132-243-234-162.nip.io:2083')
  })
})

describe('publicFailoverAttemptTimeoutMs', () => {
  it('caps hive wait so cells are tried quickly if hive TCP is blocked', () => {
    const hiveMs = publicFailoverAttemptTimeoutMs('https://132-243-234-162.nip.io', 20000, {
      hiveHost: '132-243-234-162.nip.io',
      hiveIp: '132.243.234.162',
    })
    const cellMs = publicFailoverAttemptTimeoutMs('http://87.58.213.193:9100', 20000, {
      hiveHost: '132-243-234-162.nip.io',
      hiveIp: '132.243.234.162',
    })
    assert.equal(hiveMs, 4000)
    assert.equal(cellMs, 8000)
  })
})
