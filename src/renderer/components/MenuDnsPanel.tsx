import { useState } from 'react'
import {
  DNS_PRESETS,
  DNS_PRESET_CUSTOM,
  MAX_CUSTOM_SERVERS,
  dnsDescription,
  getCustomDnsRaw,
  getDnsPreset,
  sanitizeCustomServers,
  setCustomDns,
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
  const [customInput, setCustomInput] = useState(() => getCustomDnsRaw())
  const [pending, setPending] = useState<DnsPreset | null>(null)
  const [was, setWas] = useState(() => dnsDescription())

  const customServers = sanitizeCustomServers(customInput)
  const customTouched = customInput.trim().length > 0
  const locked = vpnConnected

  const apply = (next: DnsPreset) => {
    if (next.id === 'custom') {
      const saved = setCustomDns(customInput)
      if (!saved) {
        setPending(null)
        return
      }
      setCustomInput(saved)
    }
    setDnsPreset(next)
    setPresetState(next)
    setPending(null)
    setWas(dnsDescription())
  }

  const options: DnsPreset[] = [...DNS_PRESETS]

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
        По умолчанию DNS выдаёт сервер Silent. Можно выбрать публичный или указать свой.
        Применяется при следующем подключении VPN.
      </p>

      {locked && (
        <p className="text-xs mb-3" style={{ color: muted }}>
          Отключите VPN перед сменой DNS.
        </p>
      )}

      <div className="flex flex-col gap-1">
        {options.map(option => (
          <DnsOptionRow
            key={option.id}
            option={option}
            selected={preset.id === option.id}
            disabled={locked}
            fg={fg}
            muted={muted}
            onSelect={() => setPending(option)}
          />
        ))}
      </div>

      <div className="my-3 h-px w-full" style={{ background: muted, opacity: 0.2 }} />

      <DnsOptionRow
        option={{
          ...DNS_PRESET_CUSTOM,
          subtitle: customServers || DNS_PRESET_CUSTOM.subtitle,
        }}
        selected={preset.id === 'custom'}
        disabled={locked || !customServers}
        fg={fg}
        muted={muted}
        onSelect={() => setPending(DNS_PRESET_CUSTOM)}
      />

      <input
        type="text"
        value={customInput}
        onChange={e => setCustomInput(e.target.value)}
        disabled={locked}
        placeholder="1.1.1.1, 8.8.8.8"
        spellCheck={false}
        className="w-full mt-1 px-3 py-2 rounded-xl text-sm bg-transparent border outline-none disabled:opacity-45"
        style={{ color: fg, borderColor: muted }}
      />
      <p
        className="text-[11px] mt-1.5"
        style={{ color: customTouched && !customServers ? '#EF4444' : muted }}
      >
        {customTouched && !customServers
          ? 'Нужны IP-адреса, например 1.1.1.1 или 2606:4700:4700::1111'
          : `IPv4 или IPv6, до ${MAX_CUSTOM_SERVERS} адресов через запятую`}
      </p>
      <button
        type="button"
        disabled={locked || !customServers}
        onClick={() => setPending(DNS_PRESET_CUSTOM)}
        className="w-full mt-2 px-3 py-2 rounded-xl text-sm font-semibold border disabled:opacity-45"
        style={{ color: fg, borderColor: muted }}
      >
        Использовать свой DNS
      </button>

      {pending && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4">
          <div
            className="w-full max-w-sm rounded-xl p-4 shadow-lg"
            style={{ background: 'var(--bg, #fff)', color: fg }}
          >
            <div className="text-sm font-semibold mb-2">Сменить DNS?</div>
            <p className="text-xs mb-4 leading-relaxed" style={{ color: muted }}>
              Было: {was}
              <br />
              Будет: {pending.title}
              {pending.id === 'custom'
                ? customServers && ` (${customServers})`
                : pending.servers && ` (${pending.servers})`}
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

interface RowProps {
  option: DnsPreset
  selected: boolean
  disabled: boolean
  fg: string
  muted: string
  onSelect: () => void
}

function DnsOptionRow({ option, selected, disabled, fg, muted, onSelect }: RowProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => {
        if (disabled) return
        onSelect()
      }}
      className="w-full flex items-start gap-3 px-2 py-2.5 rounded-lg text-left transition-colors disabled:opacity-45"
      style={{ color: fg }}
    >
      <span
        className="mt-1 w-4 h-4 rounded-full border-2 shrink-0 flex items-center justify-center"
        style={{ borderColor: selected ? fg : muted }}
      >
        {selected && <span className="w-2 h-2 rounded-full" style={{ background: fg }} />}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium">{option.title}</span>
        <span className="block text-xs" style={{ color: muted }}>{option.subtitle}</span>
      </span>
    </button>
  )
}
