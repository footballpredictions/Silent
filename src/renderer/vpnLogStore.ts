/** Живой лог VPN — как WdttTunnelManager.logs / LogEntry на Android. */

export interface LogEntry {
  key: string
  message: string
  count: number
  priority: number
  isError: boolean
}

const MAX_ENTRIES = 600
let entries: LogEntry[] = []
let listeners: Array<(items: LogEntry[]) => void> = []

function notify() {
  const snapshot = [...entries]
  listeners.forEach(l => l(snapshot))
}

function sortEntries(list: LogEntry[]): LogEntry[] {
  return [...list].sort((a, b) => {
    if (a.priority !== b.priority) return a.priority - b.priority
    if (a.isError !== b.isError) return a.isError ? 1 : -1
    return a.key.localeCompare(b.key)
  })
}

export function updateLog(key: string, message: string, priority: number, isError = false) {
  const idx = entries.findIndex(e => e.key === key)
  if (idx !== -1) {
    const cur = entries[idx]
    entries[idx] = { ...cur, message, count: cur.count + 1, priority, isError: cur.isError || isError }
  } else {
    entries.push({ key, message, count: 1, priority, isError })
    if (entries.length > MAX_ENTRIES) entries = entries.slice(-MAX_ENTRIES)
  }
  entries = sortEntries(entries)
  notify()
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
  notify()
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
}) {
  if (!payload.key || !payload.message) return
  updateLog(payload.key, payload.message, payload.priority ?? 1, payload.isError ?? false)
}
