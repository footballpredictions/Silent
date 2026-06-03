export type LogLevel = 'I' | 'W' | 'E'

export interface DebugLogItem {
  ts: number
  tag: string
  level: LogLevel
  message: string
}

const KEY = 'silent_debug_logs'
const MAX_ITEMS = 500

let listeners: Array<(items: DebugLogItem[]) => void> = []

function read(): DebugLogItem[] {
  try {
    const raw = localStorage.getItem(KEY)
    const arr = raw ? (JSON.parse(raw) as DebugLogItem[]) : []
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function write(items: DebugLogItem[]) {
  localStorage.setItem(KEY, JSON.stringify(items.slice(-MAX_ITEMS)))
  const snapshot = readLogs()
  listeners.forEach(l => l(snapshot))
}

export function readLogs(): DebugLogItem[] {
  return read().slice().sort((a, b) => a.ts - b.ts)
}

export function clearLogs() {
  localStorage.removeItem(KEY)
  listeners.forEach(l => l([]))
}

export function subscribeLogs(cb: (items: DebugLogItem[]) => void): () => void {
  listeners.push(cb)
  cb(readLogs())
  return () => {
    listeners = listeners.filter(l => l !== cb)
  }
}

export function pushLog(tag: string, message: string, level: LogLevel = 'I') {
  const items = read()
  items.push({ ts: Date.now(), tag, level, message: String(message ?? '') })
  write(items)
}
