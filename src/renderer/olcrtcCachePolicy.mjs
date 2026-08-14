/**
 * Dual-cache isolation for olcrtc2 (TM / WB).
 * ESM (.mjs) — Vite named import + node:test.
 */
export const OLCRTC_TELEMOST = 'telemost'
export const OLCRTC_WBSTREAM = 'wbstream'

export function normalizeOlcrtcProvider(raw) {
  const p = String(raw || '').trim().toLowerCase()
  return p === OLCRTC_WBSTREAM ? OLCRTC_WBSTREAM : OLCRTC_TELEMOST
}

export function shouldAcceptOlcrtcAssign({
  enabled,
  cryptoKeyLen,
  providerEnabled,
  room,
  denied,
  poolDenied,
} = {}) {
  if (!enabled || Number(cryptoKeyLen) !== 64) return false
  if (denied === true) return false
  if (providerEnabled === false) return false
  const r = String(room || '').trim()
  if (!r) return false
  if (poolDenied === true && !r) return false
  return true
}

export function isolateOlcrtcCachePayload(cfg, forProvider) {
  if (!cfg || typeof cfg !== 'object') return null
  const prov = normalizeOlcrtcProvider(forProvider)
  const slot = cfg.providers?.[prov]
  if (!slot || typeof slot !== 'object') return null
  if (
    !shouldAcceptOlcrtcAssign({
      enabled: cfg.enabled,
      cryptoKeyLen: (cfg.crypto_key || '').length,
      providerEnabled: slot.enabled,
      room: slot.room,
      denied: slot.denied,
      poolDenied: cfg.pool_denied,
    })
  ) {
    return null
  }
  return { ...cfg, providers: { [prov]: slot } }
}
