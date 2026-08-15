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
  BYPASS_FAMILY_OLCRTC,
  BYPASS_FAMILY_OLCRTC2,
  getOlcrtcProvider,
  setOlcrtcProvider,
  getCachedOlcrtcConfigForProvider,
  shouldRefreshOlcrtcSlot,
  refreshOlcrtcSlotFast,
  getOlcrtcCacheAgeMs,
  OLCRTC_TELEMOST,
  OLCRTC_WBSTREAM,
  bypassFamilyLabel,
  olcrtcProviderLabel,
} from '../bypassStore'
import { vkCredStrategyLabel } from '../vkCredStore'

type Props = {
  fg: string
  muted: string
  bg: string
  surface?: string
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
      className="flex items-center cursor-pointer"
      style={{ opacity: enabled ? 1 : 0.45, padding: '8px 0' }}
    >
      <span
        className="shrink-0 rounded-full flex items-center justify-center"
        style={{
          width: 20,
          height: 20,
          border: `2px solid ${selected ? fg : muted}`,
          boxSizing: 'border-box',
        }}
        aria-hidden
      >
        {selected ? (
          <span className="rounded-full" style={{ width: 10, height: 10, background: fg }} />
        ) : null}
      </span>
      <input
        type="radio"
        checked={selected}
        disabled={!enabled}
        onChange={() => enabled && onSelect()}
        className="sr-only"
      />
      <div className="text-sm font-medium" style={{ color: fg, marginLeft: 8 }}>{title}</div>
    </label>
  )
}

function familyName(family: string): string {
  return family === BYPASS_FAMILY_OLCRTC2 || family === BYPASS_FAMILY_OLCRTC ? 'olcrtc' : 'VK'
}

/** Как 1.0.160: «VK → olcrtc», внутри семейства — «Яндекс Телемост → WB Stream». */
function applyDialogLine(
  family: string,
  selFamily: string,
  vkMode: string,
  selVk: string,
  olcProvider: string,
  selOlc: string,
): string {
  const from = familyName(family)
  const to = familyName(selFamily)
  if (from !== to) return `${from} → ${to}`
  if (selFamily === BYPASS_FAMILY_OLCRTC2 && selOlc !== olcProvider) {
    return `${olcrtcProviderLabel(olcProvider)} → ${olcrtcProviderLabel(selOlc)}`
  }
  if (selFamily === BYPASS_FAMILY_WDTT && selVk !== vkMode) {
    return `${vkCredStrategyLabel(vkMode)} → ${vkCredStrategyLabel(selVk)}`
  }
  return `${from} → ${to}`
}

/**
 * Как 1.0.160 / Android: радио ставят pending, подтверждение — диалог «Применить?».
 */
export default function MenuBypassPanel({
  fg,
  muted,
  bg,
  surface,
  primary,
  vpnRunning,
  onBack,
}: Props) {
  const [family, setFamily] = useState(getBypassFamily())
  const [vkMode, setVkMode] = useState(getVkCredStrategy())
  const [olcProvider, setOlcProvider] = useState(getOlcrtcProvider())
  const [pendingFamily, setPendingFamily] = useState<string | null>(null)
  const [pendingVk, setPendingVk] = useState<string | null>(null)
  const [pendingOlc, setPendingOlc] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const switchLocked = busy || vpnRunning

  useEffect(() => {
    if (!isDebugBuild) {
      setBypassFamily(BYPASS_FAMILY_WDTT)
    }
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

  const selFamily = pendingFamily ?? family
  const selVk = pendingVk ?? vkMode
  const selOlc = pendingOlc ?? olcProvider
  const hasPending =
    (pendingFamily != null && pendingFamily !== family) ||
    (pendingVk != null && pendingVk !== vkMode) ||
    (pendingOlc != null && pendingOlc !== olcProvider)

  const clearPending = () => {
    setPendingFamily(null)
    setPendingVk(null)
    setPendingOlc(null)
  }

  useEffect(() => {
    if (!vpnRunning) return
    clearPending()
    setHint('Отключите VPN перед сменой варианта обхода.')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vpnRunning])

  const applyPending = async () => {
    if (busy || !hasPending) return
    const nextFamily = pendingFamily ?? family
    const nextVk = pendingVk ?? vkMode
    const nextOlc = pendingOlc ?? olcProvider
    const willChange =
      nextFamily !== family || nextVk !== vkMode || nextOlc !== olcProvider
    clearPending()
    setBusy(true)
    setHint(null)
    try {
      if (willChange && vpnRunning) {
        setHint('Сначала отключите VPN, затем меняйте вариант обхода.')
        return
      }

      if (nextFamily !== family) {
        setBypassFamily(nextFamily)
        setFamily(getBypassFamily())
      }
      if (nextVk !== vkMode) {
        setVkCredStrategy(nextVk)
        setVkMode(nextVk)
      }
      if (nextOlc !== olcProvider) {
        setOlcrtcProvider(nextOlc)
        setOlcProvider(getOlcrtcProvider())
      }

      const appliedFamily = getBypassFamily()
      const appliedOlc = getOlcrtcProvider()
      if (appliedFamily === BYPASS_FAMILY_OLCRTC2) {
        const cfg = getCachedOlcrtcConfigForProvider(appliedOlc)
        const room = cfg?.providers?.[appliedOlc]?.room?.trim() || ''
        const switchedProvider = nextOlc !== olcProvider
        const needRefresh = shouldRefreshOlcrtcSlot(appliedOlc, {
          force: switchedProvider,
          maxAgeMs: 8 * 60 * 1000,
        })
        setHint(
          room
            ? `Выбрано: ${olcrtcProviderLabel(appliedOlc)} · ${room.slice(0, 28)} (кеш)`
            : `Выбрано: ${olcrtcProviderLabel(appliedOlc)} — нет кеша (включите VK)`,
        )
        if (needRefresh) {
          setHint(`Выбрано: ${olcrtcProviderLabel(appliedOlc)} · обновляем слот…`)
          void refreshOlcrtcSlotFast(appliedOlc, 15_000).then(({ ok, room: nextRoom }) => {
            const ageSec = Math.floor((getOlcrtcCacheAgeMs(appliedOlc) || 0) / 1000)
            if (ok && nextRoom) {
              setHint(`Обновлено: ${olcrtcProviderLabel(appliedOlc)} · ${nextRoom.slice(0, 28)} (age ${ageSec}s)`)
            } else {
              const fallbackRoom =
                getCachedOlcrtcConfigForProvider(appliedOlc)?.providers?.[appliedOlc]?.room?.trim() || ''
              setHint(
                fallbackRoom
                  ? `Оставлен кеш: ${olcrtcProviderLabel(appliedOlc)} · ${fallbackRoom.slice(0, 28)}`
                  : `Оставлен кеш: ${olcrtcProviderLabel(appliedOlc)} · нет room`,
              )
            }
          })
        }
      } else {
        setHint(`Выбрано: ${bypassFamilyLabel(appliedFamily)}`)
      }
    } finally {
      setBusy(false)
    }
  }

  const btnBg = primary || fg
  const btnFg = bg

  return (
    <div className="relative flex flex-col h-full p-4 min-h-0">
      <button type="button" onClick={onBack} className="text-xs self-start mb-4 hover:opacity-70" style={{ color: muted }}>
        ← Назад
      </button>
      <h2 className="text-sm font-semibold mb-3" style={{ color: fg }}>Варианты обхода</h2>
      {hint ? (
        <p className="text-[11px] mb-2" style={{ color: muted }}>{hint}</p>
      ) : null}
      {vpnRunning ? (
        <p className="text-[11px] mb-2" style={{ color: muted }}>
          Переключение недоступно: VPN активен.
        </p>
      ) : null}

      <div className="flex-1 overflow-y-auto min-h-0">
        <ModeOption
          title="VK"
          selected={selFamily === BYPASS_FAMILY_WDTT}
          enabled={!switchLocked}
          fg={fg}
          muted={muted}
          onSelect={() => setPendingFamily(BYPASS_FAMILY_WDTT)}
        />
        {selFamily === BYPASS_FAMILY_WDTT && (
          <div style={{ paddingLeft: 12 }}>
            <ModeOption
              title="VKCalls"
              selected={selVk === VK_CRED_VKCALLS}
              enabled={!switchLocked}
              fg={fg}
              muted={muted}
              onSelect={() => {
                setPendingFamily(BYPASS_FAMILY_WDTT)
                setPendingVk(VK_CRED_VKCALLS)
              }}
            />
            <ModeOption
              title="Авто капча"
              selected={selVk === VK_CRED_AUTO}
              enabled={!switchLocked}
              fg={fg}
              muted={muted}
              onSelect={() => {
                setPendingFamily(BYPASS_FAMILY_WDTT)
                setPendingVk(VK_CRED_AUTO)
              }}
            />
            <ModeOption
              title="Вручную"
              selected={selVk === VK_CRED_MANUAL}
              enabled={!switchLocked}
              fg={fg}
              muted={muted}
              onSelect={() => {
                setPendingFamily(BYPASS_FAMILY_WDTT)
                setPendingVk(VK_CRED_MANUAL)
              }}
            />
          </div>
        )}

        <div style={{ height: 8 }} />
        <ModeOption
          title="olcrtc"
          selected={selFamily === BYPASS_FAMILY_OLCRTC2}
          enabled={!switchLocked}
          fg={fg}
          muted={muted}
          onSelect={() => setPendingFamily(BYPASS_FAMILY_OLCRTC2)}
        />
        {selFamily === BYPASS_FAMILY_OLCRTC2 && (
          <div style={{ paddingLeft: 12 }}>
            <ModeOption
              title="Яндекс Телемост"
              selected={selOlc === OLCRTC_TELEMOST}
              enabled={!switchLocked}
              fg={fg}
              muted={muted}
              onSelect={() => {
                setPendingFamily(BYPASS_FAMILY_OLCRTC2)
                setPendingOlc(OLCRTC_TELEMOST)
              }}
            />
            <ModeOption
              title="WB Stream"
              selected={selOlc === OLCRTC_WBSTREAM}
              enabled={!switchLocked}
              fg={fg}
              muted={muted}
              onSelect={() => {
                setPendingFamily(BYPASS_FAMILY_OLCRTC2)
                setPendingOlc(OLCRTC_WBSTREAM)
              }}
            />
          </div>
        )}
      </div>

      {(hasPending && !switchLocked) && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center px-6"
          style={{ background: 'rgba(0,0,0,0.46)' }}
          onClick={() => {
            if (!busy) clearPending()
          }}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="bypass-apply-title"
            className="w-full max-w-[280px] px-6 pt-5 pb-4"
            style={{
              background: surface || bg,
              color: fg,
              borderRadius: 28,
              boxShadow: '0 8px 28px rgba(0,0,0,0.45)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div id="bypass-apply-title" className="text-[22px] font-normal leading-7 mb-3">
              Применить?
            </div>
            <p className="text-sm leading-5 mb-6" style={{ color: muted }}>
              {applyDialogLine(family, selFamily, vkMode, selVk, olcProvider, selOlc)}
            </p>
            <div className="flex justify-end items-center gap-2">
                <button
                  type="button"
                  className="px-3 py-2 text-sm"
                  style={{ color: `${fg}99` }}
                  onClick={clearPending}
                >
                  Отмена
                </button>
                <button
                  type="button"
                  className="px-4 py-1.5 text-sm font-medium"
                  style={{ background: btnBg, color: btnFg, borderRadius: 20 }}
                  onClick={() => void applyPending()}
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
