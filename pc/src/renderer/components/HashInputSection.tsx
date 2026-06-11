import { useState } from 'react'
import { authStrings as s } from '../authStrings'
import type { ClientTheme } from '../clientTheme'
import type { themeToUi } from '../clientTheme'

type Ui = ReturnType<typeof themeToUi>

export default function HashInputSection({
  bootstrapHash,
  statusMsg,
  bootstrapConnecting,
  bootstrapReady,
  onConnect,
  ui,
  theme,
  compact,
}: {
  bootstrapHash: string | null
  statusMsg: string
  bootstrapConnecting: boolean
  bootstrapReady: boolean
  onConnect: (raw: string) => void
  ui: Ui
  theme: ClientTheme | null
  compact?: boolean
}) {
  const [input, setInput] = useState(bootstrapHash || '')

  const title = theme?.login_step1_title || s.step1Title
  const hint = theme?.login_step1_instruction || s.step1Hint
  const placeholder = theme?.login_hash_placeholder || s.hashPlaceholder
  const confirmBtn = theme?.login_hash_button_text || s.connectBtn
  const vkUrl = theme?.login_vk_pc_url || 'https://vk.com/calls'
  const vkLabel = theme?.login_vk_pc_link_text || 'VK Звонки в браузере'
  const linkColor = theme?.login_link_color || ui.linkColor

  const showCountdown = bootstrapReady && statusMsg.toLowerCase().includes('осталось')

  const buttonText = bootstrapConnecting
    ? s.connecting
    : bootstrapReady
      ? s.connectedBtn
      : confirmBtn

  const buttonEnabled = input.trim().length > 0 && !bootstrapConnecting && !bootstrapReady

  const statusColor = (() => {
    if (bootstrapReady) return ui.green
    const low = statusMsg.toLowerCase()
    if (
      low.includes('ошиб') ||
      low.includes('не удалось') ||
      low.includes('невер') ||
      low.includes('истекло') ||
      low.includes('интернет через vpn')
    ) {
      return ui.red
    }
    if (bootstrapConnecting) return ui.hint
    if (low.includes('канал готов') || low.includes('осталось')) return ui.green
    return ui.hint
  })()

  const openVkLink = () => {
    ;(window as any).electronAPI?.openExternal?.(vkUrl)
  }

  return (
    <div className={compact ? '' : 'mb-4'}>
      <p className="text-[13px] font-semibold" style={{ color: ui.fg }}>
        {title}
      </p>
      {showCountdown ? (
        <p className="text-[12px] mt-1.5 mb-2 font-medium" style={{ color: ui.green }}>
          {statusMsg}
        </p>
      ) : (
        <p className="text-[11px] mt-1 mb-2 leading-relaxed" style={{ color: ui.hint }}>
          {hint}
        </p>
      )}
      <button
        type="button"
        onClick={openVkLink}
        className="text-[11px] mb-2 underline hover:opacity-80 text-left"
        style={{ color: linkColor, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
      >
        {vkLabel}
      </button>
      <input
        className="w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none disabled:opacity-50"
        style={{
          background: ui.fieldBg,
          color: ui.fieldText,
          border: `1px solid ${ui.border}`,
        }}
        placeholder={placeholder}
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
        className="w-full mt-2.5 py-2.5 rounded-xl text-[13px] font-medium transition-opacity"
        style={{
          background: bootstrapReady ? ui.green : ui.primaryBtnBg,
          color: bootstrapReady ? '#FFFFFF' : ui.primaryBtnFg,
          opacity: buttonEnabled || bootstrapReady || bootstrapConnecting ? 1 : 0.45,
        }}
      >
        {buttonText}
      </button>
      {(statusMsg || bootstrapConnecting) && !showCountdown && (
        <p className="text-[11px] mt-2 font-medium" style={{ color: statusColor }}>
          {bootstrapConnecting && !statusMsg ? s.connectingWait : statusMsg}
        </p>
      )}
      {!compact && <div className="my-4" style={{ borderTop: `1px solid ${ui.divider}` }} />}
    </div>
  )
}
