import api, { getDeviceFingerprint, isLoggedIn } from './api'
import { isTunnelApiActive } from './tunnelApi'
import { pushLog } from './debugLog'

const DEBOUNCE_MS = 5 * 60 * 1000
const lastReportMs = new Map<string, number>()
const pendingQueue: Array<{ hash: string; errorType: string; message: string }> = []
let flushTimer: ReturnType<typeof setTimeout> | null = null

export function resetHashFailureReporter() {
  lastReportMs.clear()
  pendingQueue.length = 0
  if (flushTimer) {
    clearTimeout(flushTimer)
    flushTimer = null
  }
}

function debounceKey(hash: string, errorType: string) {
  return `${hash.slice(0, 32)}|${errorType}`
}

async function postHashFailure(hash: string, errorType: string, message: string) {
  if (!isLoggedIn()) return
  const fp = getDeviceFingerprint()
  await api.post('/api/vpn/hashes/report-failure', {
    hash,
    error_type: errorType,
    message: message.slice(0, 500),
    device_fingerprint: fp,
  })
}

export async function reportHashFailure(hash: string, errorType: string, message: string) {
  const h = hash.trim()
  if (h.length < 6) return
  const type = (errorType || 'unknown').trim().slice(0, 64)
  const key = debounceKey(h, type)
  const now = Date.now()
  if (now - (lastReportMs.get(key) || 0) < DEBOUNCE_MS) return
  lastReportMs.set(key, now)

  if (!isTunnelApiActive()) {
    pendingQueue.push({ hash: h, errorType: type, message })
    scheduleFlushPending()
    pushLog('HashFail', `queued (no tunnel): ${h.slice(0, 8)}… ${type}`, 'W')
    return
  }

  try {
    await postHashFailure(h, type, message)
    pushLog('HashFail', `reported ${h.slice(0, 8)}… ${type}`, 'I')
  } catch (e) {
    pendingQueue.push({ hash: h, errorType: type, message })
    scheduleFlushPending()
    pushLog('HashFail', `report failed: ${(e as Error)?.message || e}`, 'W')
  }
}

function scheduleFlushPending() {
  if (flushTimer) return
  flushTimer = setTimeout(() => {
    flushTimer = null
    void flushPendingHashFailures()
  }, 3000)
}

export async function flushPendingHashFailures() {
  if (!pendingQueue.length || !isTunnelApiActive() || !isLoggedIn()) return
  const batch = pendingQueue.splice(0, pendingQueue.length)
  for (const item of batch) {
    try {
      await postHashFailure(item.hash, item.errorType, item.message)
    } catch {
      pendingQueue.push(item)
    }
  }
}
