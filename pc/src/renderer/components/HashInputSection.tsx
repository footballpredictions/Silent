import { useState } from 'react'
import { authStrings as s } from '../authStrings'
import type { themeToUi } from '../clientTheme'

type Ui = ReturnType<typeof themeToUi>

export default function HashInputSection({
  bootstrapHash,
  statusMsg,
  bootstrapConnecting,
  bootstrapReady,
  onConnect,
  ui,
}: {
  bootstrapHash: string | null
  statusMsg: string
  bootstrapConnecting: boolean
  bootstrapReady: boolean
  onConnect: (raw: string) => void
  ui: Ui
}) {
  const [input, setInput] = useState(bootstrapHash || '')

  const buttonText = bootstrapConnecting
    ? s.connecting
    : bootstrapReady
      ? s.connectedBtn
      : s.connectBtn

  const buttonEnabled = input.trim().length > 0 && !bootstrapConnecting && !bootstrapReady

  const statusColor = (() => {
    if (bootstrapReady) return ui.green
    const low = statusMsg.toLowerCase()
    if (
      low.includes('ошиб') ||
      low.includes('не удалось') ||
      low.includes('невер') ||
      low.includes('истекло')
    ) {
      return ui.red
    }
    if (bootstrapConnecting) return ui.hint
    if (low.includes('канал готов') || low.includes('осталось')) return ui.green
    return ui.hint
  })()

  return (
    <div className="mb-4">
      <p className="text-[13px] font-semibold" style={{ color: ui.fg }}>
        {s.step1Title}
      </p>
      <p className="text-[11px] mt-1 mb-2" style={{ color: ui.hint }}>
        {s.step1Hint}
      </p>
      <input
        className="w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none disabled:opacity-50"
        style={{
          background: ui.fieldBg,
          color: ui.fieldText,
          border: `1px solid ${ui.border}`,
        }}
        placeholder={s.hashPlaceholder}
        value={input}
        disabled={bootstrapReady}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && buttonEnabled) onConnect(input)
        }}
      />
      <button
        type="button"
        disabled={!buttonEnabled && !bootstrapReady}
        onClick={() => onConnect(input)}
        className="w-full mt-2.5 py-2.5 rounded-xl text-[13px] font-medium"
        style={{
          background: bootstrapReady ? ui.green : ui.primaryBtnBg,
          color: bootstrapReady ? '#FFFFFF' : ui.primaryBtnFg,
          opacity: buttonEnabled || bootstrapReady || bootstrapConnecting ? 1 : 0.45,
        }}
      >
        {buttonText}
      </button>
      {(statusMsg || bootstrapConnecting) && (
        <p className="text-[11px] mt-2 font-medium" style={{ color: statusColor }}>
          {bootstrapConnecting && !statusMsg ? s.connectingWait : statusMsg}
        </p>
      )}
      <div className="my-4" style={{ borderTop: `1px solid ${ui.divider}` }} />
    </div>
  )
}
