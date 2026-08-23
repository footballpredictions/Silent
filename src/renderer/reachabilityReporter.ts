import api, { isLoggedIn } from './api'
import { getBypassFamily, getPreferredServer } from './bypassStore'
import { getAppVersion } from './updateCheck'
import { pushLog } from './debugLog'

/**
 * Репорт агенту доступности: на какой стадии сорвалось подключение.
 *
 * Отказ обычно и означает, что отправить сразу не получилось, поэтому репорт
 * кладётся в очередь и уходит, когда связь появится. Возраст (`age_sec`) сервер
 * использует, чтобы отнести отказ к нужному окну, а не к моменту доставки.
 *
 * В отличие от `hashFailureReporter` очередь не привязана к `isTunnelApiActive()`:
 * при основном VPN этот флаг всегда false, и репорты никогда бы не отправились.
 * Вместо проверки канала просто пробуем POST — main IPC сам ходит tunnel → public → соты.
 */

export type ReachabilityStage = 'dns' | 'tcp' | 'tls' | 'handshake' | 'tunnel_dead' | 'api'

export interface ReachabilityFailure {
  stage: ReachabilityStage
  tunnelUptimeSec?: number | null
  detail?: string
}

interface QueuedReport extends ReachabilityFailure {
  at: number
  serverSlot: string
  transport: string
  attempts: number
}

const DEBOUNCE_MS = 5 * 60 * 1000
/** Дольше сервер репорт всё равно не хранит и отвечает `stale`. */
const MAX_AGE_MS = 48 * 60 * 60 * 1000
const MAX_QUEUE = 40
const MAX_ATTEMPTS = 6
const RETRY_BASE_MS = 15_000
const RETRY_MAX_MS = 10 * 60 * 1000

const lastReportMs = new Map<string, number>()
const pendingQueue: QueuedReport[] = []
let flushTimer: ReturnType<typeof setTimeout> | null = null
let flushing = false

export function resetReachabilityReporter() {
  lastReportMs.clear()
  pendingQueue.length = 0
  if (flushTimer) {
    clearTimeout(flushTimer)
    flushTimer = null
  }
}

function transportName(): string {
  return getBypassFamily() === 'olcrtc2' ? 'olcrtc' : 'udp'
}

/** На ПК тип сети не определить надёжно; различаем только «связи нет совсем». */
function networkType(): string {
  return navigator.onLine ? 'ethernet' : 'offline'
}

function ageSec(at: number): number {
  return Math.max(0, Math.round((Date.now() - at) / 1000))
}

async function post(item: QueuedReport): Promise<void> {
  await api.post('/api/vpn/reachability-report', {
    stage: item.stage,
    transport: item.transport,
    network_type: networkType(),
    server_slot: item.serverSlot,
    tunnel_uptime_sec: item.tunnelUptimeSec ?? null,
    platform: 'pc',
    app_version: getAppVersion(),
    detail: (item.detail || '').slice(0, 400),
    age_sec: ageSec(item.at),
  })
}

function enqueue(item: QueuedReport) {
  pendingQueue.push(item)
  if (pendingQueue.length > MAX_QUEUE) pendingQueue.splice(0, pendingQueue.length - MAX_QUEUE)
  scheduleFlush(item.attempts)
}

function scheduleFlush(attempts = 0) {
  if (flushTimer) return
  const delay = Math.min(RETRY_MAX_MS, RETRY_BASE_MS * Math.pow(2, Math.max(0, attempts)))
  flushTimer = setTimeout(() => {
    flushTimer = null
    void flushPendingReachabilityReports()
  }, delay)
}

export async function reportReachabilityFailure(failure: ReachabilityFailure) {
  const slot = getPreferredServer()
  const key = `${failure.stage}|${slot}`
  const now = Date.now()
  if (now - (lastReportMs.get(key) || 0) < DEBOUNCE_MS) return
  lastReportMs.set(key, now)

  const item: QueuedReport = {
    ...failure,
    at: now,
    serverSlot: slot,
    transport: transportName(),
    attempts: 0,
  }

  if (!isLoggedIn()) {
    enqueue(item)
    return
  }
  try {
    await post(item)
    pushLog('Reach', `${failure.stage} → отправлен (${slot})`, 'I')
  } catch (e) {
    item.attempts = 1
    enqueue(item)
    pushLog('Reach', `${failure.stage} в очереди: ${(e as Error)?.message || e}`, 'W')
  }
}

export async function flushPendingReachabilityReports() {
  if (flushing || !pendingQueue.length || !isLoggedIn()) return
  flushing = true
  try {
    const batch = pendingQueue.splice(0, pendingQueue.length)
    for (const item of batch) {
      if (Date.now() - item.at > MAX_AGE_MS || item.attempts >= MAX_ATTEMPTS) continue
      try {
        await post(item)
      } catch {
        item.attempts += 1
        enqueue(item)
      }
    }
  } finally {
    flushing = false
  }
}

export function pendingReachabilityCount(): number {
  return pendingQueue.length
}
