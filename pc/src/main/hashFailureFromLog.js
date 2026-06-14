/** Классификация ошибок libclient — что слать на backend как «хеш сломан». */

function isTransientHashError(message) {
  const m = String(message || '').toLowerCase()
  if (!m) return true
  if (m.includes('captcha_wait') || m.includes('captcha')) return true
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

/**
 * @returns {{ hash: string, errorType: string, message: string } | null}
 */
function parseHashFailureFromLine(line, ctx) {
  const lineTrim = String(line || '').trim()
  if (!lineTrim || !ctx?.sessionVkHashes?.length) return null

  const groupCred = lineTrim.match(/\[ГРУППА #(\d+)\] Ошибка кредов: (.+)/)
  if (groupCred && ctx.tunnelReady) {
    const gid = parseInt(groupCred[1], 10)
    const msg = groupCred[2].trim()
    if (isTransientHashError(msg)) return null
    const hash = resolveHashForGroup(gid, ctx.groupHashPrefix, ctx.sessionVkHashes)
    if (!hash) return null
    return { hash, errorType: 'creds_failed', message: msg.slice(0, 500) }
  }

  const groupHash = lineTrim.match(/\[ГРУППА #(\d+)\] Запрос кредов \(хеш: (\S+)/)
  if (groupHash) {
    const gid = parseInt(groupHash[1], 10)
    ctx.groupHashPrefix.set(gid, groupHash[2].replace(/\.$/, ''))
    return null
  }

  if (lineTrim.includes('[VK Auth] Failed') && ctx.tunnelReady) {
    const stream = lineTrim.match(/\[STREAM (\d+)\]/)
    if (stream) {
      const gid = Math.floor(parseInt(stream[1], 10) / 100)
      if (gid > 0) {
        const msg = lineTrim
        if (isTransientHashError(msg)) return null
        const hash = resolveHashForGroup(gid, ctx.groupHashPrefix, ctx.sessionVkHashes)
        if (!hash) return null
        return { hash, errorType: 'vk_auth_failed', message: msg.slice(0, 500) }
      }
    }
  }

  if (
    (lineTrim.includes('хеш мёртв') || /call not found/i.test(lineTrim)) &&
    ctx.tunnelReady
  ) {
    const hashFromLine = lineTrim.match(/хеш[:]\s*(\S+)/i)?.[1]
      || lineTrim.match(/hash[:]\s*(\S+)/i)?.[1]
    const hash = hashFromLine || ctx.sessionVkHashes[0]
    if (!hash || hash.length < 6) return null
    return { hash, errorType: 'hash_dead', message: lineTrim.slice(0, 500) }
  }

  if (
    lineTrim.includes('Фатальная ошибка') &&
    (lineTrim.includes('хеш мёртв') || lineTrim.includes('FATAL_AUTH')) &&
    ctx.tunnelReady
  ) {
    const worker = lineTrim.match(/\[ВОРКЕР #(\d+)\]/)
    const gid = worker ? Math.floor(parseInt(worker[1], 10) / 100) || 1 : 1
    if (lineTrim.includes('FATAL_AUTH')) return null
    const hash = resolveHashForGroup(gid, ctx.groupHashPrefix, ctx.sessionVkHashes)
    if (!hash) return null
    return { hash, errorType: 'hash_dead', message: lineTrim.slice(0, 500) }
  }

  return null
}

module.exports = { parseHashFailureFromLine, isTransientHashError, resolveHashForGroup }
