import { useEffect, useMemo, useState } from 'react'
import { clearLogs, readLogs, subscribeLogs, type DebugLogItem } from '../debugLog'

export function DebugLogButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-1.5 py-0 text-[10px] font-medium hover:text-white transition-colors"
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
      className="absolute inset-0 z-[100] flex items-center justify-center p-3"
      style={{ WebkitAppRegion: 'no-drag', background: 'rgba(0,0,0,0.55)' } as React.CSSProperties}
    >
      <div
        className="w-[95%] h-[85%] rounded-2xl flex flex-col overflow-hidden"
        style={{ background: '#111827' }}
      >
        <div
          className="flex items-center gap-1 px-3 py-2"
          style={{ background: '#1F2937' }}
        >
          <div className="flex-1 text-[13px] font-semibold text-white">Лог VPN (debug)</div>
          <button
            type="button"
            onClick={copyLog}
            className="text-[11px] px-2 py-1 text-[#60A5FA] hover:opacity-80"
          >
            Копировать
          </button>
          <button
            type="button"
            onClick={clearLogs}
            className="text-[11px] px-2 py-1 text-[#9CA3AF] hover:text-white"
          >
            Очистить
          </button>
          <button
            type="button"
            onClick={onClose}
            className="text-[11px] px-2 py-1 text-[#9CA3AF] hover:text-white"
          >
            Закрыть
          </button>
        </div>

        <div className="flex-1 overflow-auto p-2">
          <pre
            className="text-[10px] leading-[14px] whitespace-pre-wrap break-words font-mono m-0"
            style={{ color: '#E5E7EB' }}
          >
            {logText || 'Лог пуст. Подключите VPN или привяжите VK.'}
          </pre>
        </div>
      </div>
    </div>
  )
}
