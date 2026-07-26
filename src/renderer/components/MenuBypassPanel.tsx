import { useEffect, useState } from 'react'
import {
  BYPASS_FAMILY_OLCRTC,
  BYPASS_FAMILY_WDTT,
  OLCRTC_TELEMOST,
  OLCRTC_WBSTREAM,
  VK_CRED_AUTO,
  VK_CRED_MANUAL,
  VK_CRED_VKCALLS,
  bypassFamilyLabel,
  getBypassFamily,
  getOlcrtcProvider,
  getVkCredStrategy,
  prefetchOlcrtcConfig,
  setBypassFamily,
  setOlcrtcProvider,
  setVkCredStrategy,
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
  selected,
  enabled,
  fg,
  muted,
  onSelect,
}: {
  title: string
  selected: boolean
  enabled: boolean
  fg: string
  muted: string
  onSelect: () => void
}) {
  return (
    <label
      className="flex items-center gap-2.5 py-2 cursor-pointer"
      style={{ opacity: enabled ? 1 : 0.45 }}
    >
      <span
        className="shrink-0 w-4 h-4 rounded-full border-2 flex items-center justify-center"
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
      <div className="text-sm font-medium" style={{ color: fg }}>{title}</div>
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

  const btnBg = primary || fg
  const btnFg = bg || '#FFFFFF'

  useEffect(() => {
    void prefetchOlcrtcConfig()
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
    void prefetchOlcrtcConfig()
  }

  const cancel = () => {
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
    <div className="relative flex flex-col h-full p-4 overflow-y-auto">
      <button type="button" onClick={onBack} className="text-xs self-start mb-2 hover:opacity-70" style={{ color: muted }}>
        ← Назад
      </button>
      <h2 className="text-base font-bold mb-4" style={{ color: fg }}>Варианты обхода</h2>
      {vpnRunning && (
        <p className="text-xs mb-3" style={{ color: muted }}>
          Отключите VPN перед сменой варианта.
        </p>
      )}

      <ModeOption
        title="VK"
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
            selected={(pendingVk || vkMode) === VK_CRED_VKCALLS}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingVk(VK_CRED_VKCALLS)}
          />
          <ModeOption
            title="Авто капча"
            selected={(pendingVk || vkMode) === VK_CRED_AUTO}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingVk(VK_CRED_AUTO)}
          />
          <ModeOption
            title="Ручная капча"
            selected={(pendingVk || vkMode) === VK_CRED_MANUAL}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingVk(VK_CRED_MANUAL)}
          />
        </div>
      )}

      <ModeOption
        title="olcrtc"
        selected={effectiveFamily === BYPASS_FAMILY_OLCRTC}
        enabled={!vpnRunning}
        fg={fg}
        muted={muted}
        onSelect={() => setPendingFamily(BYPASS_FAMILY_OLCRTC)}
      />
      {effectiveFamily === BYPASS_FAMILY_OLCRTC && (
        <div className="ml-3 mb-2 border-l pl-3" style={{ borderColor: `${muted}44` }}>
          <ModeOption
            title="Яндекс Телемост"
            selected={(pendingOlc || olcProvider) === OLCRTC_TELEMOST}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingOlc(OLCRTC_TELEMOST)}
          />
          <ModeOption
            title="WB Stream"
            selected={(pendingOlc || olcProvider) === OLCRTC_WBSTREAM}
            enabled={!vpnRunning}
            fg={fg}
            muted={muted}
            onSelect={() => setPendingOlc(OLCRTC_WBSTREAM)}
          />
        </div>
      )}

      {hasPending && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.45)' }}
          onClick={cancel}
          onKeyDown={(e) => { if (e.key === 'Escape') cancel() }}
          role="presentation"
        >
          <div
            className="w-full max-w-sm rounded-2xl p-4 shadow-xl space-y-4"
            style={{ background: bg || '#1a1a1a', color: fg }}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="bypass-apply-title"
          >
            <div id="bypass-apply-title" className="text-base font-semibold">Применить?</div>
            <div className="text-sm" style={{ color: muted }}>
              {bypassFamilyLabel(family)}
              {pendingFamily ? ` → ${bypassFamilyLabel(pendingFamily)}` : ''}
            </div>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                className="px-3 py-1.5 rounded-lg text-sm"
                style={{ color: muted }}
                onClick={cancel}
              >
                Отмена
              </button>
              <button
                type="button"
                className="px-3 py-1.5 rounded-lg text-sm font-medium"
                style={{ background: btnBg, color: btnFg }}
                onClick={apply}
              >
                Применить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
