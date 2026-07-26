import { useState } from 'react'
import {
  DNS_PRESETS,
  getDnsPreset,
  setDnsPreset,
  type DnsPreset,
} from '../dnsPreset'

interface Props {
  fg: string
  muted: string
  onBack: () => void
  vpnConnected?: boolean
}

export default function MenuDnsPanel({ fg, muted, onBack, vpnConnected = false }: Props) {
  const [preset, setPresetState] = useState(() => getDnsPreset())
  const [pending, setPending] = useState<DnsPreset | null>(null)

  const apply = (next: DnsPreset) => {
    setDnsPreset(next)
    setPresetState(next)
    setPending(null)
  }

  return (
    <div className="flex-1 p-4 overflow-y-auto w-full">
      <button
        type="button"
        onClick={onBack}
        className="text-xs mb-4 flex items-center gap-1"
        style={{ color: muted }}
      >
        ← Назад
      </button>

      <h2 className="text-sm font-semibold mb-1" style={{ color: fg }}>DNS</h2>
      <p className="text-[11px] mb-4 leading-relaxed" style={{ color: muted }}>
        Только debug-сборка. В release DNS не из этого меню. Применяется при следующем подключении VPN.
      </p>

      {vpnConnected && (
        <p className="text-xs mb-3" style={{ color: muted }}>
          Отключите VPN перед сменой DNS.
        </p>
      )}

      <div className="flex flex-col gap-1">
        {DNS_PRESETS.map(option => {
          const selected = preset.id === option.id
          const disabled = vpnConnected
          return (
            <button
              key={option.id}
              type="button"
              disabled={disabled}
              onClick={() => {
                if (disabled || option.id === preset.id) return
                setPending(option)
              }}
              className="w-full flex items-start gap-3 px-2 py-2.5 rounded-lg text-left transition-colors disabled:opacity-45"
              style={{ color: fg }}
            >
              <span
                className="mt-1 w-4 h-4 rounded-full border-2 shrink-0 flex items-center justify-center"
                style={{ borderColor: selected ? fg : muted }}
              >
                {selected && (
                  <span className="w-2 h-2 rounded-full" style={{ background: fg }} />
                )}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{option.title}</span>
                <span className="block text-xs" style={{ color: muted }}>{option.subtitle}</span>
              </span>
            </button>
          )
        })}
      </div>

      {pending && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4">
          <div
            className="w-full max-w-sm rounded-xl p-4 shadow-lg"
            style={{ background: 'var(--bg, #fff)', color: fg }}
          >
            <div className="text-sm font-semibold mb-2">Сменить DNS?</div>
            <p className="text-xs mb-4 leading-relaxed" style={{ color: muted }}>
              Было: {preset.title}
              <br />
              Будет: {pending.title} ({pending.servers})
              <br />
              <br />
              Переподключите VPN, чтобы применить.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPending(null)}
                className="px-3 py-1.5 text-sm rounded-lg"
                style={{ color: muted }}
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={() => apply(pending)}
                className="px-3 py-1.5 text-sm rounded-lg font-medium"
                style={{ color: fg }}
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
