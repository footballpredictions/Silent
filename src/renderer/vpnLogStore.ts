/** Живой лог VPN — как WdttTunnelManager.logs / LogEntry на Android. */

export interface LogEntry {
  key: string
  message: string
  count: number
  priority: number
  isError: boolean
}

const MAX_ENTRIES = 600
const NOTIFY_MS = 150

let entries: LogEntry[] = []
let listeners: Array<(items: LogEntry[]) => void> = []
let notifyTimer: ReturnType<typeof setTimeout> | null = null
let dirty = false

function notifyNow() {
  notifyTimer = null
  if (!dirty) return
  dirty = false
  const snapshot = [...entries]
  listeners.forEach(l => l(snapshot))
}

function scheduleNotify() {
  dirty = true
  if (notifyTimer) return
  notifyTimer = setTimeout(notifyNow, NOTIFY_MS)
}

function sortEntries(list: LogEntry[]): LogEntry[] {
  return [...list].sort((a, b) => {
    if (a.priority !== b.priority) return a.priority - b.priority
    if (a.isError !== b.isError) return a.isError ? 1 : -1
    return a.key.localeCompare(b.key)
  })
}

function applyUpdate(key: string, message: string, priority: number, isError: boolean, hits = 1) {
  const idx = entries.findIndex(e => e.key === key)
  if (idx !== -1) {
    const cur = entries[idx]
    entries[idx] = {
      ...cur,
      message,
      count: cur.count + hits,
      priority,
      isError: cur.isError || isError,
    }
  } else {
    entries.push({ key, message, count: hits, priority, isError })
    if (entries.length > MAX_ENTRIES) entries = entries.slice(-MAX_ENTRIES)
  }
}

export function updateLog(key: string, message: string, priority: number, isError = false) {
  applyUpdate(key, message, priority, isError, 1)
  entries = sortEntries(entries)
  scheduleNotify()
}

export function updateLogBatch(
  items: Array<{ key: string; message: string; priority?: number; isError?: boolean; hits?: number }>,
) {
  if (!items.length) return
  for (const item of items) {
    if (!item.key || !item.message) continue
    applyUpdate(item.key, item.message, item.priority ?? 1, item.isError ?? false, item.hits ?? 1)
  }
  entries = sortEntries(entries)
  scheduleNotify()
}

export function pushAppLog(tag: string, message: string, level: 'I' | 'W' | 'E' = 'I') {
  const priority = level === 'E' ? 99 : level === 'W' ? 50 : 1
  const key = `app_${tag}_${message.slice(0, 40).replace(/\d+/g, '#')}`
  updateLog(key, `${tag}: ${message}`, priority, level === 'E')
}

export function readVpnLogs(): LogEntry[] {
  return [...entries]
}

export function clearVpnLogs() {
  entries = []
  dirty = true
  notifyNow()
}

export function subscribeVpnLogs(cb: (items: LogEntry[]) => void): () => void {
  listeners.push(cb)
  cb(readVpnLogs())
  return () => {
    listeners = listeners.filter(l => l !== cb)
  }
}

export function ingestWdttLog(payload: {
  key?: string
  message?: string
  priority?: number
  isError?: boolean
  _hits?: number
}) {
  if (!payload.key || !payload.message) return
  updateLogBatch([
    {
      key: payload.key,
      message: payload.message,
      priority: payload.priority ?? 1,
      isError: payload.isError ?? false,
      hits: payload._hits ?? 1,
    },
  ])
}

export function ingestWdttLogBatch(
  batch: Array<{
    key?: string
    message?: string
    priority?: number
    isError?: boolean
    _hits?: number
  }>,
) {
  if (!Array.isArray(batch) || !batch.length) return
  updateLogBatch(
    batch
      .filter(p => p.key && p.message)
      .map(p => ({
        key: p.key as string,
        message: p.message as string,
        priority: p.priority ?? 1,
        isError: p.isError ?? false,
        hits: p._hits ?? 1,
      })),
  )
}
