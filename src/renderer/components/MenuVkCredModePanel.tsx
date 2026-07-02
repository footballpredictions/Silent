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
  vpnRunning: boolean
  onBack: () => void
}

function ModeOption({
  title,
  subtitle,
  selected,
  enabled,
  fg,
  onSelect,
}: {
  title: string
  subtitle: string
  selected: boolean
  enabled: boolean
  fg: string
  onSelect: () => void
}) {
  return (
    <label
      className="flex items-start gap-2 py-2 cursor-pointer"
      style={{ opacity: enabled ? 1 : 0.45 }}
    >
      <input
        type="radio"
        checked={selected}
        disabled={!enabled}
        onChange={() => enabled && onSelect()}
        className="mt-1 shrink-0"
      />
      <div>
        <div className="text-sm font-medium" style={{ color: fg }}>{title}</div>
        <div className="text-xs leading-snug mt-0.5" style={{ color: mutedColor(fg) }}>{subtitle}</div>
      </div>
    </label>
  )
}

function mutedColor(fg: string) {
  return fg.includes('rgb') ? fg : `${fg}99`
}

export default function MenuVkCredModePanel({ fg, muted, vpnRunning, onBack }: Props) {
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
        onSelect={() => setPending(VK_CRED_VKCALLS)}
      />
      <ModeOption
        title="Авто капча"
        subtitle="Legacy + невидимый WBV Auto, затем ручной WebView"
        selected={mode === VK_CRED_AUTO}
        enabled={!vpnRunning}
        fg={fg}
        onSelect={() => setPending(VK_CRED_AUTO)}
      />
      <ModeOption
        title="Ручная капча"
        subtitle="Legacy + только видимый WebView"
        selected={mode === VK_CRED_MANUAL}
        enabled={!vpnRunning}
        fg={fg}
        onSelect={() => setPending(VK_CRED_MANUAL)}
      />

      {pending && pending !== mode && (
        <div
          className="mt-4 p-3 rounded-xl text-xs space-y-3"
          style={{ background: 'rgba(255,255,255,0.06)', color: fg }}
        >
          <div>
            Было: {vkCredStrategyLabel(mode)}
            <br />
            Будет: {vkCredStrategyLabel(pending)}
            <br />
            <span style={{ color: muted }}>Применится при следующем подключении VPN.</span>
          </div>
          <div className="flex gap-2">
            <button type="button" className="px-3 py-1 rounded-lg text-xs font-medium" style={{ background: '#2563EB', color: '#fff' }} onClick={() => apply(pending)}>
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
