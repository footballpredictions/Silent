import { useEffect, useState } from 'react'
import { isDebugBuild } from '../debugBuild'
import {
  VK_CRED_AUTO,
  VK_CRED_MANUAL,
  VK_CRED_VKCALLS,
  getVkCredStrategy,
  setBypassFamily,
  setVkCredStrategy,
  BYPASS_FAMILY_WDTT,
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

/** Debug: режимы VK-креденшалов. Olcrtc убран. */
export default function MenuBypassPanel({ fg, muted, bg, primary, vpnRunning, onBack }: Props) {
  const [vkMode, setVkMode] = useState(getVkCredStrategy())
  const [pendingVk, setPendingVk] = useState<string | null>(null)

  const btnBg = primary || fg
  const btnFg = bg || '#FFFFFF'

  useEffect(() => {
    setBypassFamily(BYPASS_FAMILY_WDTT)
  }, [])

  if (!isDebugBuild) {
    return (
      <div className="relative flex flex-col h-full p-4 overflow-y-auto">
        <button type="button" onClick={onBack} className="text-xs self-start mb-4 hover:opacity-70" style={{ color: muted }}>
          ← Назад
        </button>
        <h2 className="text-sm font-semibold mb-3" style={{ color: fg }}>Обход</h2>
        <p className="text-[12px]" style={{ color: muted }}>
          Только VK / WDTT. Другие варианты отключены.
        </p>
      </div>
    )
  }

  const apply = () => {
    if (pendingVk) {
      setVkCredStrategy(pendingVk)
      setVkMode(pendingVk)
    }
    setPendingVk(null)
  }

  const hasPending = pendingVk && pendingVk !== vkMode

  return (
    <div className="relative flex flex-col h-full p-4 overflow-y-auto">
      <button type="button" onClick={onBack} className="text-xs self-start mb-4 hover:opacity-70" style={{ color: muted }}>
        ← Назад
      </button>
      <h2 className="text-sm font-semibold mb-3" style={{ color: fg }}>VK (debug)</h2>
      {vpnRunning && (
        <p className="text-[11px] mb-3" style={{ color: muted }}>
          Отключите VPN перед сменой режима.
        </p>
      )}
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
      {hasPending && (
        <div
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.45)' }}
        >
          <div className="w-full max-w-sm rounded-xl p-4 border" style={{ background: bg || '#111', borderColor: `${muted}44` }}>
            <p className="text-sm mb-3" style={{ color: fg }}>Применить режим VK?</p>
            <div className="flex gap-2 justify-end">
              <button type="button" className="text-xs px-3 py-1.5" style={{ color: muted }} onClick={() => setPendingVk(null)}>
                Отмена
              </button>
              <button
                type="button"
                className="text-xs px-3 py-1.5 rounded"
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
