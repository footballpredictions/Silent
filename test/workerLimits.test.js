const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const {
  effectiveConnectWorkers,
  WORKERS_PER_GROUP,
  LEGACY_CAPTCHA_TARGET_WORKERS,
} = require('../src/main/workerLimits')

describe('effectiveConnectWorkers', () => {
  it('VK Calls keeps full stream_count (63)', () => {
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: false, vkAuthMode: 'vkcalls', streamCount: 63 }),
      63,
    )
  })

  it('legacy auto/manual captcha targets 27 (boot 9 separately)', () => {
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: false, vkAuthMode: 'legacy', streamCount: 63 }),
      LEGACY_CAPTCHA_TARGET_WORKERS,
    )
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: false, vkAuthMode: 'legacy', streamCount: 108 }),
      LEGACY_CAPTCHA_TARGET_WORKERS,
    )
    assert.equal(LEGACY_CAPTCHA_TARGET_WORKERS, 27)
    assert.equal(WORKERS_PER_GROUP, 9)
  })

  it('legacy does not exceed stream_count when lower', () => {
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: false, vkAuthMode: 'legacy', streamCount: 18 }),
      18,
    )
  })

  it('bootstrap is not capped by legacy rule', () => {
    assert.equal(
      effectiveConnectWorkers({ isBootstrap: true, vkAuthMode: 'legacy', streamCount: 3 }),
      3,
    )
  })
})
