/**
 * Dual-cache isolation: fetch TM must not overwrite WB slot.
 * Запуск: npm test
 */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import {
  isolateOlcrtcCachePayload,
  shouldAcceptOlcrtcAssign,
} from '../src/renderer/olcrtcCachePolicy.mjs'

const crypto64 = 'a'.repeat(64)

function cfgBoth() {
  return {
    enabled: true,
    crypto_key: crypto64,
    pool_denied: false,
    providers: {
      telemost: { enabled: true, room: 'tm-room', denied: false },
      wbstream: { enabled: true, room: 'wb-room', denied: false },
    },
  }
}

describe('olcrtc dual-cache', () => {
  it('isolates requested provider — sibling dropped', () => {
    const isolated = isolateOlcrtcCachePayload(cfgBoth(), 'telemost')
    assert.ok(isolated)
    assert.equal(isolated.providers.telemost.room, 'tm-room')
    assert.equal(isolated.providers.wbstream, undefined)
  })

  it('WB fetch does not keep Telemost slot in payload', () => {
    const isolated = isolateOlcrtcCachePayload(cfgBoth(), 'wbstream')
    assert.ok(isolated)
    assert.equal(isolated.providers.wbstream.room, 'wb-room')
    assert.equal(isolated.providers.telemost, undefined)
  })

  it('rejects denied / empty / short crypto', () => {
    assert.equal(
      shouldAcceptOlcrtcAssign({
        enabled: true,
        cryptoKeyLen: 32,
        providerEnabled: true,
        room: 'r',
        denied: false,
      }),
      false,
    )
    assert.equal(
      isolateOlcrtcCachePayload(
        { enabled: true, crypto_key: crypto64, providers: { telemost: { enabled: true, room: '', denied: false } } },
        'telemost',
      ),
      null,
    )
    assert.equal(
      isolateOlcrtcCachePayload(
        {
          enabled: true,
          crypto_key: crypto64,
          providers: { telemost: { enabled: true, room: 'x', denied: true } },
        },
        'telemost',
      ),
      null,
    )
  })
})
