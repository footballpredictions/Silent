import TelegramIcon from './TelegramIcon'

const DEFAULT_CHANNEL = 'https://t.me/silentvpn3'
const DEFAULT_SUPPORT = 'https://t.me/silentvpn3?direct'

function openUrl(url: string) {
  const api = (window as { electronAPI?: { openExternal?: (u: string) => void } }).electronAPI
  if (api?.openExternal) {
    void api.openExternal(url)
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

function TelegramLink({
  url,
  label,
  muted,
}: {
  url: string
  label: string
  muted: string
}) {
  return (
    <button
      type="button"
      onClick={() => openUrl(url)}
      className="flex flex-col items-center gap-2 min-w-[72px] hover:opacity-80 transition-opacity"
      title={label}
    >
      <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center">
        <TelegramIcon size={28} color="#000000" />
      </div>
      <span className="text-xs" style={{ color: muted }}>
        {label}
      </span>
    </button>
  )
}

export default function SupportTelegramLinks({
  channelUrl,
  supportUrl,
  muted,
}: {
  channelUrl?: string | null
  supportUrl?: string | null
  muted: string
}) {
  const channel = (channelUrl || '').trim() || DEFAULT_CHANNEL
  const support = (supportUrl || '').trim() || DEFAULT_SUPPORT

  return (
    <div className="flex items-start gap-8 mt-2">
      <TelegramLink url={channel} label="Канал" muted={muted} />
      <TelegramLink url={support} label="Поддержка" muted={muted} />
    </div>
  )
}
