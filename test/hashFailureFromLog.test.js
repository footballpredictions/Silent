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
  it('does not report the logged VK internal error as a broken hash', () => {
    const state = ctx(true)
    parseHashFailureFromLine('[ГРУППА #7] Запрос кредов (хеш: abcdef12...)', state)
    const got = parseHashFailureFromLine('[ГРУППА #7] Ошибка кредов: step=step3 messages.getAnonymCallToken kind=vk_api: error_code=10 Internal server error — пропуск группы (9 воркеров)', state)
    assert.equal(got, null)
  })

  it('resolves the truncated log prefix to a complete known hash', () => {
    const state = ctx(true)
    parseHashFailureFromLine('[ГРУППА #7] Запрос кредов (хеш: abcdef12...)', state)
    const got = parseHashFailureFromLine('[ГРУППА #7] Ошибка кредов: call not found', state)
    assert.equal(got.hash, 'abcdef1234567890hashslot0')
  })

  it('does not send an unknown truncated prefix to the backend', () => {
    const state = ctx(true)
    parseHashFailureFromLine('[ГРУППА #7] Запрос кредов (хеш: unknown1...)', state)
    assert.equal(parseHashFailureFromLine('[ГРУППА #7] Ошибка кредов: call not found', state), null)
  })

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
