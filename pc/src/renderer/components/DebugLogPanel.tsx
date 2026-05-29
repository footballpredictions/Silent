import { useEffect, useMemo, useState } from 'react'
import { clearLogs, readLogs, subscribeLogs, type DebugLogItem } from '../debugLog'

export function DebugLogButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-2 py-1 rounded text-[10px] border border-gray-700 text-gray-300 hover:text-white hover:border-gray-500"
      style={{ WebkitAppRegion: 'no-drag' } as any}
      title="Логи"
    >
      LOG
    </button>
  )
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  return d.toLocaleTimeString('ru-RU', { hour12: false })
}

function rowColor(level: DebugLogItem['level']): string {
  if (level === 'E') return 'text-red-300'
  if (level === 'W') return 'text-amber-300'
  return 'text-gray-200'
}

export default function DebugLogPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<DebugLogItem[]>(readLogs())

  useEffect(() => subscribeLogs(setItems), [])

  const rows = useMemo(() => items.slice(-300), [items])

  if (!open) return null

  return (
    <div className="absolute inset-0 z-[100] bg-black/60 p-3" style={{ WebkitAppRegion: 'no-drag' } as any}>
      <div className="w-full h-full rounded-xl bg-[#0f0f0f] border border-[#2a2a2a] flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-[#2a2a2a] flex items-center justify-between">
          <div className="text-xs text-white font-semibold">Debug log</div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={clearLogs}
              className="text-[10px] px-2 py-1 rounded border border-[#444] text-[#bbb] hover:text-white"
            >
              Очистить
            </button>
            <button
              type="button"
              onClick={onClose}
              className="text-[10px] px-2 py-1 rounded border border-[#444] text-[#bbb] hover:text-white"
            >
              Закрыть
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-2 font-mono text-[10px] leading-4">
          {rows.length === 0 ? (
            <div className="text-[#777]">Логов пока нет</div>
          ) : (
            rows.map((r, idx) => (
              <div key={`${r.ts}-${idx}`} className={rowColor(r.level)}>
                [{formatTime(r.ts)}] [{r.level}] [{r.tag}] {r.message}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
