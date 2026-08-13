import { useEffect, useState } from 'react'
import { isDebugBuild } from '../debugBuild'
import {
  VK_CRED_AUTO,
  VK_CRED_MANUAL,
  VK_CRED_VKCALLS,
  getVkCredStrategy,
  setBypassFamily,
  setVkCredStrategy,
  getBypassFamily,
  BYPASS_FAMILY_WDTT,
  BYPASS_FAMILY_OLCRTC2,
  getOlcrtcProvider,
  setOlcrtcProvider,
  getCachedOlcrtcConfigForProvider,
  OLCRTC_TELEMOST,
  OLCRTC_WBSTREAM,
  bypassFamilyLabel,
  olcrtcProviderLabel,
} from '../bypassStore'

type Props = {
  fg: string
  muted: string
  bg: string
  primary: string
  vpnRunning: boolean
  onBack: () => void
  /** После смены провайдера при живом VPN — UI сбросит тумблер. */
  onVpnStoppedForSwitch?: () => void
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

/**
 * Как Android: VK | olcrtc → Телемост | WB.
 * Выбор применяется сразу (без кнопки «Применить» / диалога).
 * При живом VPN — стоп, потом смена (как Apply-switch на Android).
 */
export default function MenuBypassPanel({
  fg,
  muted,
  bg,
  primary,
  vpnRunning,
  onBack,
  onVpnStoppedForSwitch,
}: Props) {
  const [family, setFamily] = useState(getBypassFamily())
  const [vkMode, setVkMode] = useState(getVkCredStrategy())
  const [olcProvider, setOlcProvider] = useState(getOlcrtcProvider())
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState<string | null>(null)

  useEffect(() => {
    if (!isDebugBuild) {
      setBypassFamily(BYPASS_FAMILY_WDTT)
    }
    // Конфиг TM/WB — только login / sync при VK, не при открытии меню.
  }, [])

  if (!isDebugBuild) {
    return (
      <div className="relative flex flex-col h-full p-4 overflow-y-auto">
        <button type="button" onClick={onBack} className="text-xs self-start mb-4 hover:opacity-70" style={{ color: muted }}>
          ← Назад
        </button>
        <h2 className="text-sm font-semibold mb-3" style={{ color: fg }}>Варианты обхода</h2>
        <p className="text-[12px]" style={{ color: muted }}>
          Только VK / WDTT. olcrtc — в debug-сборке.
        </p>
      </div>
    )
  }

  const stopVpnIfNeeded = async () => {
    if (!vpnRunning) return
    setHint('Останавливаю текущий канал…')
    try {
      await (window as any).electronAPI?.vpnDisconnect?.({ fast: true })
    } catch {
      /* ignore */
    }
    onVpnStoppedForSwitch?.()
    await new Promise((r) => setTimeout(r, 400))
  }

  const applyFamily = async (next: string) => {
    if (busy || next === family) return
    setBusy(true)
    setHint(null)
    try {
      await stopVpnIfNeeded()
      setBypassFamily(next)
      setFamily(getBypassFamily())
      if (next === BYPASS_FAMILY_OLCRTC2) {
        const cfg = getCachedOlcrtcConfigForProvider(getOlcrtcProvider())
        const room = cfg?.providers?.[getOlcrtcProvider()]?.room?.trim() || ''
        setHint(
          room
            ? `Выбрано: ${bypassFamilyLabel(next)} · ${room.slice(0, 28)}`
            : `Выбрано: ${bypassFamilyLabel(next)} (нет кеша — войдите / sync VK)`,
        )
      } else {
        setHint(`Выбрано: ${bypassFamilyLabel(next)}`)
      }
    } finally {
      setBusy(false)
    }
  }

  const applyVk = async (next: string) => {
    if (busy || next === vkMode) return
    setBusy(true)
    try {
      await stopVpnIfNeeded()
      setVkCredStrategy(next)
      setVkMode(next)
      setHint(null)
    } finally {
      setBusy(false)
    }
  }

  const applyOlc = async (next: string) => {
    if (busy || next === olcProvider) return
    setBusy(true)
    setHint(null)
    try {
      await stopVpnIfNeeded()
      setOlcrtcProvider(next)
      setOlcProvider(getOlcrtcProvider())
      const cfg = getCachedOlcrtcConfigForProvider(next)
      const room = cfg?.providers?.[next]?.room?.trim() || ''
      setHint(
        room
          ? `Выбрано: ${olcrtcProviderLabel(next)} · ${room.slice(0, 28)} (кеш)`
          : `Выбрано: ${olcrtcProviderLabel(next)} — нет кеша (войдите / sync VK)`,
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex flex-col h-full p-4 overflow-y-auto">
      <button type="button" onClick={onBack} className="text-xs self-start mb-4 hover:opacity-70" style={{ color: muted }}>
        ← Назад
      </button>
      <h2 className="text-sm font-semibold mb-3" style={{ color: fg }}>Варианты обхода</h2>
      {vpnRunning && (
        <p className="text-[11px] mb-3" style={{ color: muted }}>
          Смена варианта остановит текущий VPN и применится сразу.
        </p>
      )}
      {hint ? (
        <p className="text-[11px] mb-2" style={{ color: muted }}>{hint}</p>
      ) : null}
      {busy ? (
        <p className="text-[11px] mb-2" style={{ color: primary || muted }}>Применяю…</p>
      ) : null}

      <ModeOption
        title="VK"
        selected={family === BYPASS_FAMILY_WDTT}
        enabled={!busy}
        fg={fg}
        muted={muted}
        onSelect={() => void applyFamily(BYPASS_FAMILY_WDTT)}
      />
      {family === BYPASS_FAMILY_WDTT && (
        <div className="ml-3 pl-3 border-l border-white/10">
          <ModeOption
            title="VKCalls"
            selected={vkMode === VK_CRED_VKCALLS}
            enabled={!busy}
            fg={fg}
            muted={muted}
            onSelect={() => void applyVk(VK_CRED_VKCALLS)}
          />
          <ModeOption
            title="Авто капча"
            selected={vkMode === VK_CRED_AUTO}
            enabled={!busy}
            fg={fg}
            muted={muted}
            onSelect={() => void applyVk(VK_CRED_AUTO)}
          />
          <ModeOption
            title="Вручную"
            selected={vkMode === VK_CRED_MANUAL}
            enabled={!busy}
            fg={fg}
            muted={muted}
            onSelect={() => void applyVk(VK_CRED_MANUAL)}
          />
        </div>
      )}

      <ModeOption
        title="olcrtc"
        selected={family === BYPASS_FAMILY_OLCRTC2}
        enabled={!busy}
        fg={fg}
        muted={muted}
        onSelect={() => void applyFamily(BYPASS_FAMILY_OLCRTC2)}
      />
      {family === BYPASS_FAMILY_OLCRTC2 && (
        <div className="ml-3 pl-3 border-l border-white/10">
          <ModeOption
            title="Яндекс Телемост"
            selected={olcProvider === OLCRTC_TELEMOST}
            enabled={!busy}
            fg={fg}
            muted={muted}
            onSelect={() => void applyOlc(OLCRTC_TELEMOST)}
          />
          <ModeOption
            title="WB Stream"
            selected={olcProvider === OLCRTC_WBSTREAM}
            enabled={!busy}
            fg={fg}
            muted={muted}
            onSelect={() => void applyOlc(OLCRTC_WBSTREAM)}
          />
        </div>
      )}
    </div>
  )
}
