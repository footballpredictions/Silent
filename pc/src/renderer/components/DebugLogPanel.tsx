import { useEffect, useMemo, useRef, useState } from 'react'
import { clearLogs, formatLogLine, readLogs, subscribeLogs, type DebugLogItem } from '../debugLog'

export function DebugLogButton({ onClick }: { onClick: () => void }) {
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

export default function DebugLogPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<DebugLogItem[]>(readLogs())
  const [copyToast, setCopyToast] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => subscribeLogs(setItems), [])

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [items, open])

  const logText = useMemo(() => {
    if (items.length === 0) return ''
    return items.slice(-600).map(formatLogLine).join('\n')
  }, [items])

  if (!open) return null

  const copyLog = async () => {
    const text = logText || '(пусто)'
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const api = (window as any).electronAPI
      if (api?.copyToClipboard) await api.copyToClipboard(text)
    }
    setCopyToast(true)
    setTimeout(() => setCopyToast(false), 2000)
  }

  const levelColor = (level: string) => {
    if (level === 'E') return '#F87171'
    if (level === 'W') return '#FBBF24'
    if (level === 'T') return '#93C5FD'
    if (level === 'D') return '#9CA3AF'
    return '#E5E7EB'
  }

  return (
    <div
      className="absolute inset-0 z-[100] flex items-center justify-center p-2"
      style={{ WebkitAppRegion: 'no-drag', background: 'rgba(0,0,0,0.55)' } as React.CSSProperties}
    >
      <div
        className="w-full h-[88%] rounded-2xl flex flex-col overflow-hidden"
        style={{ background: '#111827', maxWidth: 280 }}
      >
        <div className="px-2 pt-2 pb-1.5 shrink-0 relative" style={{ background: '#1F2937' }}>
          <div className="text-center">
            <div className="text-[12px] font-semibold text-white leading-tight">Лог VPN (debug)</div>
          </div>
          {copyToast && (
            <div
              className="absolute left-1/2 -translate-x-1/2 top-1 px-2 py-0.5 rounded text-[9px] text-white"
              style={{ background: 'rgba(0,0,0,0.75)' }}
            >
              Лог скопирован
            </div>
          )}
          <div className="flex gap-1 mt-2">
            <button type="button" onClick={copyLog} className="flex-1 py-1 rounded text-[9px] font-medium text-[#60A5FA] hover:bg-white/5">
              Копировать
            </button>
            <button type="button" onClick={clearLogs} className="flex-1 py-1 rounded text-[9px] font-medium text-[#9CA3AF] hover:text-white hover:bg-white/5">
              Очистить
            </button>
            <button type="button" onClick={onClose} className="flex-1 py-1 rounded text-[9px] font-medium text-[#9CA3AF] hover:text-white hover:bg-white/5">
              Закрыть
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-2 min-h-0 font-mono text-[9px] leading-[13px]">
          {items.length === 0 ? (
            <p className="text-[#9CA3AF] m-0">Лог пуст. Подключите VPN или войдите.</p>
          ) : (
            items.slice(-600).map((item, i) => (
              <div key={`${item.ts}-${i}`} style={{ color: levelColor(item.level) }}>
                {formatLogLine(item)}
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  )
}
