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

function copyViaExecCommand(text: string): boolean {
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '0'
    ta.style.width = '1px'
    ta.style.height = '1px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

/** Copy log — Electron clipboard first, then browser API, then execCommand. */
export async function copyLogText(): Promise<boolean> {
  const text = getLogText()
  const api = (window as any).electronAPI
  if (api?.copyToClipboard) {
    try {
      await api.copyToClipboard(text)
      return true
    } catch {
      /* fallback */
    }
  }
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      /* fallback */
    }
  }
  return copyViaExecCommand(text)
}

export function initVpnLogListener() {
  const api = (window as any).electronAPI
  if (!api?.onVpnLog || (window as any).__silentLogInit) return
  ;(window as any).__silentLogInit = true
  api.onVpnLog((line: string) => pushLog('VPN', line, 'D'))
}
