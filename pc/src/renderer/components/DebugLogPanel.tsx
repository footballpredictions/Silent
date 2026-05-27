import { useEffect, useRef, useState } from 'react'
import { clearLogs, copyLogText, getLogText, subscribeLogs } from '../debugLog'

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
  const [copyMsg, setCopyMsg] = useState('')
  const preRef = useRef<HTMLPreElement>(null)

  useEffect(() => subscribeLogs(() => tick(n => n + 1)), [])

  useEffect(() => {
    if (!copyMsg) return
    const t = setTimeout(() => setCopyMsg(''), 2500)
    return () => clearTimeout(t)
  }, [copyMsg])

  if (!open) return null

  const text = getLogText() || 'Лог пуст. Подключите VPN или привяжите VK.'

  const copy = async () => {
    let ok = await copyLogText()
    if (!ok && preRef.current) {
      try {
        const sel = window.getSelection()
        const range = document.createRange()
        range.selectNodeContents(preRef.current)
        sel?.removeAllRanges()
        sel?.addRange(range)
        ok = document.execCommand('copy')
        sel?.removeAllRanges()
      } catch {
        ok = false
      }
    }
    setCopyMsg(ok ? 'Скопировано' : 'Выделите текст и Ctrl+C')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3">
      <div className="flex flex-col w-full h-full max-h-[92%] bg-gray-900 rounded-2xl overflow-hidden shadow-xl">
        <div className="flex items-center gap-1 px-3 py-2 bg-gray-800 border-b border-gray-700">
          <span className="flex-1 text-xs font-semibold text-white">Лог VPN (debug)</span>
          {copyMsg && <span className="text-[10px] text-green-400">{copyMsg}</span>}
          <button type="button" onClick={copy} className="text-[11px] text-blue-400 px-2 py-1">Копировать</button>
          <button type="button" onClick={() => clearLogs()} className="text-[11px] text-gray-400 px-2 py-1">Очистить</button>
          <button type="button" onClick={onClose} className="text-[11px] text-gray-400 px-2 py-1">Закрыть</button>
        </div>
        <pre
          ref={preRef}
          className="flex-1 overflow-auto p-3 text-[10px] leading-relaxed text-gray-200 font-mono whitespace-pre-wrap break-all select-text cursor-text"
          style={{ userSelect: 'text' } as React.CSSProperties}
        >
          {text}
        </pre>
      </div>
    </div>
  )
}
