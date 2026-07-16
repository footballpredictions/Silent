const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const { effectiveConnectWorkers, WORKERS_PER_GROUP } = require('../src/main/workerLimits')

describe('effectiveConnectWorkers', () => {
  it('VK Calls keeps full stream_count (63)', () => {
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: false, vkAuthMode: 'vkcalls', streamCount: 63 }),
      63,
    )
  })

  it('legacy auto/manual captcha caps to 9', () => {
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: false, vkAuthMode: 'legacy', streamCount: 63 }),
      WORKERS_PER_GROUP,
    )
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: false, vkAuthMode: 'legacy', streamCount: 108 }),
      9,
    )
  })

  it('bootstrap is not capped by legacy rule', () => {
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: true, vkAuthMode: 'legacy', streamCount: 3 }),
      3,
    )
  })
})
