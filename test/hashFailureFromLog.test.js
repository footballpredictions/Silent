const { describe, it } = require('node:test')
const assert = require('node:assert/strict')
const {
  parseHashFailureFromLine,
  isTransientHashError,
  isStaleAnonymToken,
  isCallDeadMessage,
} = require('../src/main/hashFailureFromLog')

function ctx(ready = false) {
  return {
    sessionVkHashes: ['abcdef1234567890hashslot0'],
    groupHashPrefix: new Map(),
    tunnelReady: ready,
  }
}

describe('hashFailureFromLog', () => {
  it('does not report anonym_token.outdated', () => {
    assert.equal(isStaleAnonymToken('anonym_token.outdated'), true)
    assert.equal(isTransientHashError('LEGACY_ESCALATE anonym_token.outdated'), true)
    const line = '[STREAM 100] [VK Auth] Failed kind=okcdn_api anonym_token.outdated'
    assert.equal(parseHashFailureFromLine(line, ctx(true)), null)
    assert.equal(parseHashFailureFromLine(line, ctx(false)), null)
  })

  it('reports call not found before tunnelReady', () => {
    assert.equal(isCallDeadMessage('call not found'), true)
    const line = '[STREAM 100] [VK Auth] call not found'
    const got = parseHashFailureFromLine(line, ctx(false))
    assert.ok(got)
    assert.equal(got.errorType, 'hash_dead')
    assert.equal(got.hash, 'abcdef1234567890hashslot0')
  })
})
