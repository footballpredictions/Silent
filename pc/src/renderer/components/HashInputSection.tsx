import { useState } from 'react'
import { authColors } from '../authTheme'
import { authStrings as s } from '../authStrings'

export default function HashInputSection({
  bootstrapHash,
  statusMsg,
  bootstrapConnecting,
  bootstrapReady,
  onConnect,
}: {
  bootstrapHash: string | null
  statusMsg: string
  bootstrapConnecting: boolean
  bootstrapReady: boolean
  onConnect: (raw: string) => void
}) {
  const [input, setInput] = useState(bootstrapHash || '')

  const buttonText = bootstrapConnecting
    ? s.connecting
    : bootstrapReady
      ? s.connectedBtn
      : s.connectBtn

  const buttonEnabled = input.trim().length > 0 && !bootstrapConnecting && !bootstrapReady

  const statusColor = (() => {
    if (bootstrapReady) return authColors.green
    const low = statusMsg.toLowerCase()
    if (
      low.includes('ошиб') ||
      low.includes('не удалось') ||
      low.includes('невер') ||
      low.includes('истекло')
    ) {
      return authColors.red
    }
    return authColors.hint
  })()

  return (
    <div className="mb-4">
      <p className="text-[13px] font-semibold text-white">{s.step1Title}</p>
      <p className="text-[11px] mt-1 mb-2" style={{ color: authColors.hint }}>
        {s.step1Hint}
      </p>
      <input
        className="w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none disabled:opacity-50"
        style={{
          background: authColors.fieldBg,
          color: authColors.fieldText,
          border: `1px solid ${authColors.border}`,
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
        disabled={!buttonEnabled}
        onClick={() => onConnect(input)}
        className="w-full mt-2.5 py-2.5 rounded-xl text-[13px] font-medium disabled:opacity-100"
        style={{
          background: bootstrapReady ? authColors.green : '#FFFFFF',
          color: bootstrapReady ? '#FFFFFF' : '#000000',
          opacity: buttonEnabled || bootstrapReady ? 1 : 0.45,
        }}
      >
        {buttonText}
      </button>
      {statusMsg && (
        <p className="text-[11px] mt-2" style={{ color: statusColor }}>
          {statusMsg}
        </p>
      )}
      <div className="my-4" style={{ borderTop: `1px solid ${authColors.divider}` }} />
    </div>
  )
}
