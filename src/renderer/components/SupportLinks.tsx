import { Globe } from 'lucide-react'
import TelegramIcon from './TelegramIcon'

const DEFAULT_CHANNEL = 'https://t.me/silentvpn3'
const DEFAULT_SUPPORT = 'https://t.me/silentvpn3?direct'
const WEBSITE = 'https://silentvpn3.github.io/'

function openUrl(url: string) {
  const api = (window as { electronAPI?: { openExternal?: (u: string) => void } }).electronAPI
  if (api?.openExternal) {
    void api.openExternal(url)
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

export default function SupportLinks({
  channelUrl,
  supportUrl,
  fg,
  muted,
  surface,
}: {
  channelUrl?: string | null
  supportUrl?: string | null
  fg: string
  muted: string
  surface: string
}) {
  const channel = (channelUrl || '').trim() || DEFAULT_CHANNEL
  const support = (supportUrl || '').trim() || DEFAULT_SUPPORT
  const telegram = <TelegramIcon size={28} color="currentColor" />
  const links = [
    { label: 'Канал', url: channel, icon: telegram },
    { label: 'Поддержка', url: support, icon: telegram },
    { label: 'Сайт', url: WEBSITE, icon: <Globe size={24} strokeWidth={1.75} aria-hidden="true" /> },
  ]

  return (
    <div className="flex flex-wrap items-start gap-8 mt-2">
      {links.map(({ label, url, icon }) => (
        <button
          key={label}
          type="button"
          onClick={() => openUrl(url)}
          className="flex flex-col items-center gap-2 min-w-[72px] hover:opacity-80 transition-opacity"
          title={label}
        >
          <span className="w-12 h-12 rounded-2xl flex items-center justify-center" style={{ backgroundColor: surface, color: fg }}>
            {icon}
          </span>
          <span className="text-xs" style={{ color: muted }}>{label}</span>
        </button>
      ))}
    </div>
  )
}
