'use strict'

const RETIRED_HIVE_HOSTS = new Set(['132.243.234.162', '132-243-234-162.nip.io'])

function hostnameOf(base) {
  try {
    return new URL(String(base || '')).hostname.toLowerCase()
  } catch {
    return ''
  }
}

function isRetiredHiveBase(base) {
  const host = hostnameOf(base)
  return Boolean(host && RETIRED_HIVE_HOSTS.has(host))
}

function rewriteStoredPublicBase(raw, currentNip = 'https://89-125-188-100.nip.io') {
  const nip = String(currentNip || '').replace(/\/$/, '')
  const stored = String(raw || '').trim().replace(/\/$/, '')
  if (!stored || isRetiredHiveBase(stored)) return nip
  const host = hostnameOf(stored)
  if (/^\d+\.\d+\.\d+\.\d+$/.test(host) && nip.includes(host.replace(/\./g, '-'))) return nip
  if (host === hostnameOf(nip)) return nip
  return stored
}

function publicFailoverBases({
  hiveHost = '89-125-188-100.nip.io',
  hiveIp = '89.125.188.100',
  standby = [],
  baked = [],
  stored = '',
} = {}) {
  const out = []
  const seen = new Set()
  const add = (raw) => {
    const v = String(raw || '').replace(/\/$/, '')
    if (!v || seen.has(v) || isRetiredHiveBase(v)) return
    seen.add(v)
    out.push(v)
  }
  const hive = { hiveHost, hiveIp }
  const rest = []
  for (const u of [...baked, ...standby]) {
    if (isHivePublicBase(u, hive) || isRetiredHiveBase(u)) rest.push(u)
    else add(u)
  }
  // Соты первыми: 443 Улья из РФ часто таймаут, вход/подписка живут на :9100.
  add(`https://${hiveHost}`)
  add(`https://${hiveIp}`)
  const canon = rewriteStoredPublicBase(stored, `https://${hiveHost}`)
  if (canon && !isHivePublicBase(canon, hive) && !isRetiredHiveBase(canon)) add(canon)
  for (const u of rest) {
    if (!isRetiredHiveBase(u)) add(u)
  }
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
  isRetiredHiveBase,
  rewriteStoredPublicBase,
}
