const MAX_LINES = 600
const lines: string[] = []
const listeners = new Set<() => void>()

function ts(): string {
  const d = new Date()
  const p = (n: number, w = 2) => String(n).padStart(w, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`
}

export function pushLog(tag: string, msg: string, level: 'D' | 'I' | 'W' | 'E' = 'I') {
  lines.push(`${ts()} ${level}/${tag}: ${msg}`)
  while (lines.length > MAX_LINES) lines.shift()
  listeners.forEach(l => l())
}

export function getLogText(): string {
  return lines.join('\n')
}

export function clearLogs() {
  lines.length = 0
  listeners.forEach(l => l())
}

export function subscribeLogs(cb: () => void): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function initVpnLogListener() {
  const api = (window as any).electronAPI
  if (!api?.onVpnLog || (window as any).__silentLogInit) return
  ;(window as any).__silentLogInit = true
  api.onVpnLog((line: string) => pushLog('VPN', line, 'D'))
}
