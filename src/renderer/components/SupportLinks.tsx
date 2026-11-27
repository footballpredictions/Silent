import { Globe } from 'lucide-react'
import { useState } from 'react'
import InstallerIcon from './InstallerIcon'
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
  const desktop = (window as { electronAPI?: {
    platform?: 'pc' | 'mac' | 'linux'
    openLatestInstaller?: () => Promise<boolean>
  } }).electronAPI
  const [download, setDownload] = useState<'idle' | 'loading' | 'error'>('idle')
  const openInstaller = async () => {
    setDownload('loading')
    try {
      setDownload(await desktop?.openLatestInstaller?.() ? 'idle' : 'error')
    } catch {
      setDownload('error')
    }
  }
  const telegram = <TelegramIcon size={28} color="currentColor" />
  const links = [
    { label: 'Канал', url: channel, icon: telegram },
    { label: 'Поддержка', url: support, icon: telegram },
    { label: 'Сайт', url: WEBSITE, icon: <Globe size={24} strokeWidth={1.75} aria-hidden="true" /> },
  ]

  return (
    <div>
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
      <button
        type="button"
        onClick={() => void openInstaller()}
        disabled={download === 'loading'}
        className="flex items-center gap-3 mt-6 text-left hover:opacity-80 disabled:opacity-60 transition-opacity"
        style={{ color: fg }}
      >
        <span className="w-12 h-12 shrink-0 rounded-2xl flex items-center justify-center" style={{ backgroundColor: surface }}>
          <InstallerIcon platform={desktop?.platform ?? 'pc'} surface={surface} />
        </span>
        <span className="text-xs font-medium">{download === 'loading' ? 'Получаем ссылку…' : 'Скачать актуальную версию'}</span>
      </button>
      {download === 'error' && (
        <p className="mt-2 text-xs" role="status" style={{ color: muted }}>
          Не удалось открыть загрузку. Попробуйте снова или откройте «Сайт».
        </p>
      )}
    </div>
  )
}
