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
  // Вход/регистрация: сначала Улей; соты по очереди только если Улей не ответил.
  add(`https://${hiveHost}`)
  add(`https://${hiveIp}`)
  for (const u of baked) add(u)
  for (const u of standby) add(u)
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
