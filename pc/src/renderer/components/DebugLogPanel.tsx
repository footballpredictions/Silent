import { useEffect, useMemo, useState } from 'react'
import { clearLogs, readLogs, subscribeLogs, type DebugLogItem } from '../debugLog'

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

function formatLogText(items: DebugLogItem[]): string {
  if (items.length === 0) return ''
  return items
    .map(r => {
      const d = new Date(r.ts)
      const t = d.toLocaleTimeString('ru-RU', { hour12: false })
      return `[${t}] [${r.level}] [${r.tag}] ${r.message}`
    })
    .join('\n')
}

export default function DebugLogPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<DebugLogItem[]>(readLogs())

  useEffect(() => subscribeLogs(setItems), [])

  const logText = useMemo(() => formatLogText(items.slice(-500)), [items])

  if (!open) return null

  const copyLog = async () => {
    const text = logText || '(пусто)'
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      /* ignore */
    }
  }

  return (
    <div
      className="absolute inset-0 z-[100] flex items-center justify-center p-2"
      style={{ WebkitAppRegion: 'no-drag', background: 'rgba(0,0,0,0.55)' } as React.CSSProperties}
    >
      <div
        className="w-full h-[88%] rounded-2xl flex flex-col overflow-hidden"
        style={{ background: '#111827', maxWidth: 248 }}
      >
        <div className="px-2 pt-2 pb-1.5 shrink-0" style={{ background: '#1F2937' }}>
          <div className="text-center">
            <div className="text-[12px] font-semibold text-white leading-tight">Лог VPN</div>
            <div className="text-[9px] text-[#9CA3AF] leading-tight mt-0.5">debug</div>
          </div>
          <div className="flex gap-1 mt-2">
            <button
              type="button"
              onClick={copyLog}
              className="flex-1 min-w-0 py-1 rounded text-[9px] font-medium text-[#60A5FA] hover:bg-white/5 truncate"
            >
              Копия
            </button>
            <button
              type="button"
              onClick={clearLogs}
              className="flex-1 min-w-0 py-1 rounded text-[9px] font-medium text-[#9CA3AF] hover:text-white hover:bg-white/5 truncate"
            >
              Очистить
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex-1 min-w-0 py-1 rounded text-[9px] font-medium text-[#9CA3AF] hover:text-white hover:bg-white/5 truncate"
            >
              Закрыть
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-2 min-h-0">
          <pre
            className="text-[9px] leading-[13px] whitespace-pre-wrap break-words font-mono m-0"
            style={{ color: '#E5E7EB' }}
          >
            {logText || 'Лог пуст. Подключите VPN или привяжите VK.'}
          </pre>
        </div>
      </div>
    </div>
  )
}
