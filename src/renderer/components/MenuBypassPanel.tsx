import { useEffect, useState } from 'react'
import {
  BYPASS_FAMILY_OLCRTC,
  BYPASS_FAMILY_WDTT,
  OLCRTC_JITSI,
  OLCRTC_TELEMOST,
  OLCRTC_WBSTREAM,
  VK_CRED_AUTO,
  VK_CRED_MANUAL,
  VK_CRED_VKCALLS,
  bypassFamilyLabel,
  getBypassFamily,
  getCachedOlcrtcConfig,
  getOlcrtcProvider,
  getVkCredStrategy,
  olcrtcProviderLabel,
  prefetchOlcrtcConfig,
  setBypassFamily,
  setOlcrtcProvider,
  setVkCredStrategy,
  vkCredStrategyLabel,
} from '../bypassStore'

type Props = {
  fg: string
  muted: string
  bg: string
  primary: string
  vpnRunning: boolean
  onBack: () => void
}

function ModeOption({
  title,
  subtitle,
  selected,
  enabled,
  fg,
  muted,
  onSelect,
}: {
  title: string
  subtitle: string
  selected: boolean
  enabled: boolean
  fg: string
  muted: string
  onSelect: () => void
}) {
  return (
    <label
      className="flex items-start gap-2.5 py-2 cursor-pointer"
      style={{ opacity: enabled ? 1 : 0.45 }}
    >
      <span
        className="mt-1 shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center"
        style={{ borderColor: selected ? fg : muted }}
        aria-hidden
      >
        {selected ? (
          <span className="w-2 h-2 rounded-full" style={{ background: fg }} />
        ) : null}
      </span>
      <input
        type="radio"
        checked={selected}
        disabled={!enabled}
        onChange={() => enabled && onSelect()}
        className="sr-only"
      />
      <div>
        <div className="text-sm font-medium" style={{ color: fg }}>{title}</div>
        <div className="text-xs leading-snug mt-0.5" style={{ color: muted }}>{subtitle}</div>
      </div>
    </label>
  )
}

export default function MenuBypassPanel({ fg, muted, bg, primary, vpnRunning, onBack }: Props) {
  const [family, setFamily] = useState(getBypassFamily())
  const [vkMode, setVkMode] = useState(getVkCredStrategy())
  const [olcProvider, setOlcProvider] = useState(getOlcrtcProvider())
  const [pendingFamily, setPendingFamily] = useState<string | null>(null)
  const [pendingVk, setPendingVk] = useState<string | null>(null)
  const [pendingOlc, setPendingOlc] = useState<string | null>(null)
  const [olcCached, setOlcCached] = useState(!!getCachedOlcrtcConfig())

  const btnBg = primary || fg
  const btnFg = bg || '#FFFFFF'

  useEffect(() => {
    void prefetchOlcrtcConfig().then((c) => setOlcCached(!!c))
  }, [])

  const apply = () => {
    if (pendingFamily) {
      setBypassFamily(pendingFamily)
      setFamily(pendingFamily)
    }
    if (pendingVk) {
      setVkCredStrategy(pendingVk)
      setVkMode(pendingVk)
    }
    if (pendingOlc) {
      setOlcrtcProvider(pendingOlc)
      setOlcProvider(pendingOlc)
    }
    setPendingFamily(null)
    setPendingVk(null)
    setPendingOlc(null)
  }

  const hasPending =
    (pendingFamily && pendingFamily !== family) ||
    (pendingVk && pendingVk !== vkMode) ||
    (pendingOlc && pendingOlc !== olcProvider)

  const effectiveFamily = pendingFamily || family

  return (
    <div className="flex flex-col h-full p-4 overflow-y-auto">
      <button type="button" onClick={onBack} className="text-xs self-start mb-2 hover:opacity-70" style={{ color: muted }}>
        ← Назад
      </button>
      <h2 className="text-base font-bold mb-1" style={{ color: fg }}>Варианты обхода</h2>
      <p className="text-xs mb-4 leading-snug" style={{ color: muted }}>
        Только debug. Вход всегда через VK. Здесь выбираете, чем подключать основной VPN.
        Нужно подтверждение «Применить».
      </p>
      {vpnRunning && (
        <p className="text-xs mb-3" style={{ color: muted }}>
          Отключите VPN перед сменой варианта.
        </p>
      )}
      <p className="text-xs mb-3" style={{ color: muted }}>
        olcrtc-config: {olcCached ? 'загружен' : 'ещё нет (подтянется с публичного API)'}
      </p>

      <div className="text-xs font-semibold mb-1" style={{ color: fg }}>1. VK / WDTT</div>
      <ModeOption
        title="Вариант 1 — VK / WDTT"
        subtitle="WireGuard через VK TURN (текущий прод-путь)"
        selected={effectiveFamily === BYPASS_FAMILY_WDTT}
        enabled={!vpnRunning}
        fg={fg}
        muted={muted}
        onSelect={() => setPendingFamily(BYPASS_FAMILY_WDTT)}
      />
      {effectiveFamily === BYPASS_FAMILY_WDTT && (
        <div className="ml-3 mb-2 border-l pl-3" style={{ borderColor: `${muted}44` }}>
          <ModeOption
            title="VKCalls"
            subtitle="api.vk.me — без капчи"
            selected={(pendingVk || vkMode) === VK_CRED_VKCALLS}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingVk(VK_CRED_VKCALLS)}
          />
          <ModeOption
            title="Авто капча"
            subtitle="Legacy + WBV Auto"
            selected={(pendingVk || vkMode) === VK_CRED_AUTO}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingVk(VK_CRED_AUTO)}
          />
          <ModeOption
            title="Ручная капча"
            subtitle="Legacy + видимый WebView"
            selected={(pendingVk || vkMode) === VK_CRED_MANUAL}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingVk(VK_CRED_MANUAL)}
          />
        </div>
      )}

      <div className="text-xs font-semibold mb-1 mt-3" style={{ color: fg }}>2. olcrtc</div>
      <ModeOption
        title="Вариант 2 — olcrtc"
        subtitle="TCP-over-WebRTC: Jitsi / WB Stream / Телемост"
        selected={effectiveFamily === BYPASS_FAMILY_OLCRTC}
        enabled={!vpnRunning}
        fg={fg}
        muted={muted}
        onSelect={() => setPendingFamily(BYPASS_FAMILY_OLCRTC)}
      />
      {effectiveFamily === BYPASS_FAMILY_OLCRTC && (
        <div className="ml-3 mb-2 border-l pl-3" style={{ borderColor: `${muted}44` }}>
          <ModeOption
            title="Jitsi Meet"
            subtitle="рекомендуется datachannel"
            selected={(pendingOlc || olcProvider) === OLCRTC_JITSI}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingOlc(OLCRTC_JITSI)}
          />
          <ModeOption
            title="WB Stream"
            subtitle="vp8channel"
            selected={(pendingOlc || olcProvider) === OLCRTC_WBSTREAM}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingOlc(OLCRTC_WBSTREAM)}
          />
          <ModeOption
            title="Яндекс Телемост"
            subtitle="vp8channel"
            selected={(pendingOlc || olcProvider) === OLCRTC_TELEMOST}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingOlc(OLCRTC_TELEMOST)}
          />
        </div>
      )}

      {hasPending && (
        <div
          className="mt-4 p-3 rounded-xl text-xs space-y-3"
          style={{ background: `${fg}0F`, color: fg }}
        >
          <div>
            Семья: {bypassFamilyLabel(family)}
            {pendingFamily ? ` → ${bypassFamilyLabel(pendingFamily)}` : ''}
            <br />
            {effectiveFamily === BYPASS_FAMILY_WDTT ? (
              <>
                VK: {vkCredStrategyLabel(vkMode)}
                {pendingVk ? ` → ${vkCredStrategyLabel(pendingVk)}` : ''}
              </>
            ) : (
              <>
                Провайдер: {olcrtcProviderLabel(olcProvider)}
                {pendingOlc ? ` → ${olcrtcProviderLabel(pendingOlc)}` : ''}
              </>
            )}
            <br />
            <span style={{ color: muted }}>Применится при следующем подключении.</span>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="px-3 py-1 rounded-lg text-xs font-medium"
              style={{ background: btnBg, color: btnFg }}
              onClick={apply}
            >
              Применить
            </button>
            <button
              type="button"
              className="px-3 py-1 rounded-lg text-xs"
              style={{ color: muted }}
              onClick={() => {
                setPendingFamily(null)
                setPendingVk(null)
                setPendingOlc(null)
              }}
            >
              Отмена
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
