import { useEffect, useMemo, useRef, useState } from 'react'
import {
  clearVpnLogs,
  readVpnLogs,
  subscribeVpnLogs,
  type LogEntry,
} from '../vpnLogStore'
import { isDebugBuild } from '../debugBuild'

export function DebugLogButton({ onClick }: { onClick: () => void }) {
  if (!isDebugBuild) return null
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-1.5 py-0 text-[10px] font-medium hover:opacity-70 transition-opacity"
      style={{ WebkitAppRegion: 'no-drag', color: '#6B7280' } as React.CSSProperties}
      title="Логи"
    >
      Лог
    </button>
  )
}

function entryColor(entry: LogEntry): string {
  if (entry.isError) return '#EF4444'
  if (entry.priority <= 2) return '#34D399'
  if (entry.priority === 3) return '#60A5FA'
  return '#E5E7EB'
}

function TunnelLogLine({ entry }: { entry: LogEntry }) {
  return (
    <div className="flex items-center gap-2.5 py-[3px] w-full">
      <div
        className="shrink-0 flex items-center justify-center rounded-xl min-w-[24px] h-[22px] px-1.5"
        style={{ background: 'rgba(30, 58, 95, 0.4)' }}
      >
        <span className="text-[10px] font-bold leading-none" style={{ color: '#60A5FA' }}>
          {entry.count}
        </span>
      </div>
      <span
        className="flex-1 font-mono text-[10px] leading-[14px] break-words"
        style={{
          color: entryColor(entry),
          fontWeight: entry.isError ? 600 : 400,
        }}
      >
        {entry.message}
      </span>
    </div>
  )
}

export default function DebugLogPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<LogEntry[]>(() => (open ? readVpnLogs() : []))
  const [copyToast, setCopyToast] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const openRef = useRef(open)
  openRef.current = open

  useEffect(() => {
    if (!open) return
    setItems(readVpnLogs())
    return subscribeVpnLogs(next => {
      if (openRef.current) setItems(next)
    })
  }, [open])

  useEffect(() => {
    if (open && items.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'auto' })
    }
  }, [items.length, open])

  const logText = useMemo(() => {
    if (items.length === 0) return ''
    return items.map(e => `${e.message} (x${e.count})`).join('\n')
  }, [items])

  if (!isDebugBuild || !open) return null

  const copyLog = () => {
    const text = logText || '(пусто)'
    const api = (window as any).electronAPI
    // IPC clipboard быстрее и не блокирует renderer как navigator.clipboard в Electron
    if (api?.copyToClipboard) {
      void api.copyToClipboard(text)
    } else {
      void navigator.clipboard.writeText(text).catch(() => {})
    }
    setCopyToast(true)
    setTimeout(() => setCopyToast(false), 2000)
  }

  return (
    <div
      className="absolute inset-0 z-[100] flex items-center justify-center p-2"
      style={{ WebkitAppRegion: 'no-drag', background: 'rgba(0,0,0,0.55)' } as React.CSSProperties}
    >
      <div
        className="rounded-2xl flex flex-col overflow-hidden"
        style={{ background: '#111827', width: '95%', height: '85%', maxWidth: 320 }}
      >
        <div
          className="flex items-center shrink-0 gap-0 px-2 py-1.5 relative"
          style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}
        >
          <div className="flex-1 min-w-0 text-[11px] font-semibold text-white truncate pr-1">Лог VPN</div>
          <button type="button" onClick={copyLog} className="px-1 py-0 text-[8px] font-medium hover:opacity-80 whitespace-nowrap" style={{ color: '#60A5FA' }}>
            Копир.
          </button>
          <button type="button" onClick={clearVpnLogs} className="px-1 py-0 text-[8px] font-medium hover:opacity-80 whitespace-nowrap" style={{ color: '#9CA3AF' }}>
            Очист.
          </button>
          <button type="button" onClick={onClose} className="px-1 py-0 text-[8px] font-medium hover:opacity-80 whitespace-nowrap" style={{ color: '#9CA3AF' }}>
            Закрыть
          </button>
          {copyToast && (
            <div
              className="absolute left-1/2 -translate-x-1/2 bottom-0 translate-y-full mt-1 px-2 py-0.5 rounded text-[9px] text-white z-10"
              style={{ background: 'rgba(0,0,0,0.75)' }}
            >
              Лог скопирован
            </div>
          )}
        </div>

        <div className="flex-1 overflow-auto px-3 py-1 min-h-0">
          {items.length === 0 ? (
            <p className="text-[11px] font-mono m-0 py-2" style={{ color: '#9CA3AF' }}>
              Лог пуст. Подключите VPN.
            </p>
          ) : (
            items.map(entry => <TunnelLogLine key={entry.key} entry={entry} />)
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  )
}
