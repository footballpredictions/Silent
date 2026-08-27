/** Классификация ошибок libclient — что слать на backend как «хеш сломан». */

const CAPTCHA_REPORT_THRESHOLD = 3
const CAPTCHA_WINDOW_MS = 10 * 60 * 1000
const captchaHits = new Map()

function isCaptchaRelated(message) {
  const m = String(message || '').toLowerCase()
  return m.includes('captcha') || m.includes('капч')
}

function isPersistentCaptcha(hash) {
  const key = String(hash || '').slice(0, 32)
  if (key.length < 6) return false
  const now = Date.now()
  const hits = captchaHits.get(key) || []
  hits.push(now)
  const fresh = hits.filter((t) => now - t <= CAPTCHA_WINDOW_MS)
  captchaHits.set(key, fresh)
  return fresh.length >= CAPTCHA_REPORT_THRESHOLD
}

function resetCaptchaHits() {
  captchaHits.clear()
}

function isStaleAnonymToken(message) {
  const m = String(message || '').toLowerCase()
  return m.includes('anonym_token.outdated') ||
    (m.includes('anonym_token') && m.includes('outdated'))
}

function isCallDeadMessage(message) {
  const m = String(message || '').toLowerCase()
  return m.includes('хеш мёртв') ||
    m.includes('call not found') ||
    m.includes('invalid join link') ||
    m.includes('join link is not valid') ||
    m.includes('conversation not found')
}

function isTransientHashError(message) {
  const m = String(message || '').toLowerCase()
  if (!m) return true
  if (isStaleAnonymToken(m)) return true
  if (isCallDeadMessage(m)) return false
  if (isCaptchaRelated(m)) return true
  if (m.includes('i/o timeout') || m.includes('context deadline exceeded')) return true
  if (m.includes('connection refused') || m.includes('connection reset')) return true
  if (m.includes('rate limit') || m.includes('flood control') || m.includes('error 29')) return true
  if (m.includes('getanonymoustoken') && (m.includes('error 10') || m.includes('"error_code":10'))) return true
  if (m.includes('error 10') && m.includes('internal')) return true
  if (m.includes('timeout') && !m.includes('wrap_auth_timeout')) return true
  if (m.includes('all vk credentials failed')) return true
  if (m.includes('global lockout')) return true
  return false
}

function resolveHashForGroup(groupId, groupHashPrefix, sessionVkHashes) {
  const prefix = groupHashPrefix.get(groupId)
  if (prefix) {
    const full = sessionVkHashes.find(h => h.startsWith(prefix))
    if (full) return full
    if (prefix.length >= 6) return prefix
  }
  if (!sessionVkHashes.length) return null
  const idx = Math.max(0, groupId - 1) % sessionVkHashes.length
  return sessionVkHashes[idx]
}

function finalizeFailure(hash, errorType, message) {
  const h = String(hash || '').trim()
  if (h.length < 6) return null
  let type = String(errorType || 'unknown').trim()
  const msg = String(message || '').slice(0, 500)

  if (isStaleAnonymToken(msg)) return null

  if (isCaptchaRelated(msg) || type.toLowerCase().includes('captcha')) {
    if (!isPersistentCaptcha(h)) return null
    type = 'captcha_persistent'
  } else if (isTransientHashError(msg) && type !== 'hash_dead' && type !== 'no_connections') {
    return null
  }

  return { hash: h, errorType: type, message: msg }
}

function hashFromDeadLine(lineTrim, ctx) {
  const hashFromLine = lineTrim.match(/хеш[:]\s*(\S+)/i)?.[1]
    || lineTrim.match(/hash[:]\s*(\S+)/i)?.[1]
  if (hashFromLine && hashFromLine.length >= 6) return hashFromLine.replace(/[.,;]+$/, '')
  const stream = lineTrim.match(/\[STREAM (\d+)\]/)
  if (stream) {
    const gid = Math.floor(parseInt(stream[1], 10) / 100)
    if (gid > 0) {
      const hash = resolveHashForGroup(gid, ctx.groupHashPrefix, ctx.sessionVkHashes)
      if (hash) return hash
    }
  }
  const group = lineTrim.match(/\[ГРУППА #(\d+)\]/)
  if (group) {
    const hash = resolveHashForGroup(parseInt(group[1], 10), ctx.groupHashPrefix, ctx.sessionVkHashes)
    if (hash) return hash
  }
  return ctx.sessionVkHashes[0] || null
}

/**
 * @returns {{ hash: string, errorType: string, message: string } | null}
 */
function parseHashFailureFromLine(line, ctx) {
  const lineTrim = String(line || '').trim()
  if (!lineTrim || !ctx?.sessionVkHashes?.length) return null

  const groupHash = lineTrim.match(/\[ГРУППА #(\d+)\] Запрос кредов \(хеш: (\S+)/)
  if (groupHash) {
    const gid = parseInt(groupHash[1], 10)
    ctx.groupHashPrefix.set(gid, groupHash[2].replace(/\.$/, ''))
    return null
  }

  // Join-link мёртв — репортить и до tunnelReady (STREAM 100 на GETCONF).
  if (isCallDeadMessage(lineTrim)) {
    const hash = hashFromDeadLine(lineTrim, ctx)
    if (!hash) return null
    return finalizeFailure(hash, 'hash_dead', lineTrim)
  }

  const groupCred = lineTrim.match(/\[ГРУППА #(\d+)\] Ошибка кредов: (.+)/)
  if (groupCred && ctx.tunnelReady) {
    const gid = parseInt(groupCred[1], 10)
    const msg = groupCred[2].trim()
    const hash = resolveHashForGroup(gid, ctx.groupHashPrefix, ctx.sessionVkHashes)
    if (!hash) return null
    return finalizeFailure(hash, 'creds_failed', msg)
  }

  if (lineTrim.includes('[VK Auth] Failed') && ctx.tunnelReady) {
    const stream = lineTrim.match(/\[STREAM (\d+)\]/)
    if (stream) {
      const gid = Math.floor(parseInt(stream[1], 10) / 100)
      if (gid > 0) {
        const hash = resolveHashForGroup(gid, ctx.groupHashPrefix, ctx.sessionVkHashes)
        if (!hash) return null
        return finalizeFailure(hash, 'vk_auth_failed', lineTrim)
      }
    }
  }

  if (
    lineTrim.includes('Фатальная ошибка') &&
    lineTrim.includes('FATAL_AUTH') &&
    ctx.tunnelReady
  ) {
    return null
  }

  return null
}

module.exports = {
  parseHashFailureFromLine,
  isTransientHashError,
  isCallDeadMessage,
  isStaleAnonymToken,
  resolveHashForGroup,
  resetCaptchaHits,
  finalizeFailure,
}
