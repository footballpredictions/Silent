'use strict'

function publicFailoverBases({
  hiveHost = '132-243-234-162.nip.io',
  hiveIp = '132.243.234.162',
  standby = [],
  baked = [],
} = {}) {
  const out = []
  const seen = new Set()
  const add = (raw) => {
    const v = String(raw || '').replace(/\/$/, '')
    if (!v || seen.has(v)) return
    seen.add(v)
    out.push(v)
  }
  const hive = { hiveHost, hiveIp }
  const rest = []
  for (const u of [...baked, ...standby]) {
    if (isHivePublicBase(u, hive)) rest.push(u)
    else add(u)
  }
  // Соты первыми: 443 Улья из РФ часто таймаут, вход/подписка живут на :9100.
  add(`https://${hiveHost}`)
  add(`https://${hiveIp}`)
  for (const u of rest) add(u)
  return out
}

function isHivePublicBase(base, { hiveHost = '', hiveIp = '' } = {}) {
  try {
    const host = new URL(String(base || '')).hostname
    return Boolean(host && (host === hiveHost || host === hiveIp))
  } catch {
    return false
  }
}

function publicFailoverAttemptTimeoutMs(base, requested = 20000, hive = {}) {
  const cap = isHivePublicBase(base, hive) ? 4000 : 8000
  return Math.min(Number(requested) || 20000, cap)
}

module.exports = {
  publicFailoverBases,
  publicFailoverAttemptTimeoutMs,
  isHivePublicBase,
}
