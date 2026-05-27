import { useEffect, useState } from 'react'
import { clearLogs, getLogText, subscribeLogs } from '../debugLog'

export function DebugLogButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-[10px] text-gray-400 hover:text-gray-600 px-1"
    >
      Лог
    </button>
  )
}

export default function DebugLogPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [, tick] = useState(0)
  useEffect(() => subscribeLogs(() => tick(n => n + 1)), [])
  if (!open) return null

  const text = getLogText() || 'Лог пуст. Подключите VPN или привяжите VK.'

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      alert('Лог скопирован')
    } catch {
      alert('Не удалось скопировать')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
      <div className="flex flex-col w-full h-full max-h-[92%] bg-gray-900 rounded-2xl overflow-hidden shadow-xl">
        <div className="flex items-center gap-1 px-3 py-2 bg-gray-800 border-b border-gray-700">
          <span className="flex-1 text-xs font-semibold text-white">Лог VPN (debug)</span>
          <button type="button" onClick={copy} className="text-[11px] text-blue-400 px-2 py-1">Копировать</button>
          <button type="button" onClick={() => clearLogs()} className="text-[11px] text-gray-400 px-2 py-1">Очистить</button>
          <button type="button" onClick={onClose} className="text-[11px] text-gray-400 px-2 py-1">Закрыть</button>
        </div>
        <pre className="flex-1 overflow-auto p-3 text-[10px] leading-relaxed text-gray-200 font-mono whitespace-pre-wrap break-all">
          {text}
        </pre>
      </div>
    </div>
  )
}
