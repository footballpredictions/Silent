import { useState } from 'react'
import {
  getVkCredStrategy,
  setVkCredStrategy,
  vkCredStrategyLabel,
  VK_CRED_AUTO,
  VK_CRED_MANUAL,
  VK_CRED_VKCALLS,
} from '../vkCredStore'

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

export default function MenuVkCredModePanel({ fg, muted, bg, primary, vpnRunning, onBack }: Props) {
  const [mode, setMode] = useState(getVkCredStrategy())
  const [pending, setPending] = useState<string | null>(null)

  const apply = (next: string) => {
    if (next === mode) {
      setPending(null)
      return
    }
    setVkCredStrategy(next)
    setMode(next)
    setPending(null)
  }

  const btnBg = primary || fg
  const btnFg = bg || '#FFFFFF'

  return (
    <div className="flex flex-col h-full p-4 overflow-y-auto">
      <button type="button" onClick={onBack} className="text-xs self-start mb-2 hover:opacity-70" style={{ color: muted }}>
        ← Назад
      </button>
      <h2 className="text-base font-bold mb-1" style={{ color: fg }}>Режим VK-кредов</h2>
      <p className="text-xs mb-4 leading-snug" style={{ color: muted }}>
        Только debug-сборка. В release всегда VKCalls.
      </p>
      {vpnRunning && (
        <p className="text-xs mb-3" style={{ color: muted }}>
          Отключите VPN перед сменой режима.
        </p>
      )}

      <ModeOption
        title="VKCalls (по умолчанию)"
        subtitle="api.vk.me — без капчи, как в proxy-turn-vk-android"
        selected={mode === VK_CRED_VKCALLS}
        enabled={!vpnRunning}
        fg={fg}
        muted={muted}
        onSelect={() => setPending(VK_CRED_VKCALLS)}
      />
      <ModeOption
        title="Авто капча"
        subtitle="Запасной: boot 9 → рамп 27. Legacy + WBV Auto, затем ручной WebView"
        selected={mode === VK_CRED_AUTO}
        enabled={!vpnRunning}
        fg={fg}
        muted={muted}
        onSelect={() => setPending(VK_CRED_AUTO)}
      />
      <ModeOption
        title="Ручная капча"
        subtitle="Запасной: boot 9 → рамп 27. Legacy + только видимый WebView"
        selected={mode === VK_CRED_MANUAL}
        enabled={!vpnRunning}
        fg={fg}
        muted={muted}
        onSelect={() => setPending(VK_CRED_MANUAL)}
      />

      {pending && pending !== mode && (
        <div
          className="mt-4 p-3 rounded-xl text-xs space-y-3"
          style={{ background: `${fg}0F`, color: fg }}
        >
          <div>
            Было: {vkCredStrategyLabel(mode)}
            <br />
            Будет: {vkCredStrategyLabel(pending)}
            <br />
            <span style={{ color: muted }}>Применится при следующем подключении VPN.</span>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="px-3 py-1 rounded-lg text-xs font-medium"
              style={{ background: btnBg, color: btnFg }}
              onClick={() => apply(pending)}
            >
              Применить
            </button>
            <button type="button" className="px-3 py-1 rounded-lg text-xs" style={{ color: muted }} onClick={() => setPending(null)}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
