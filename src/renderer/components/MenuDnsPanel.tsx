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
  bg?: string
  fieldBg?: string
  borderStrong?: string
  dark?: boolean
  onBack: () => void
  vpnConnected?: boolean
}

export default function MenuDnsPanel({
  fg,
  muted,
  bg = '#0a0a0a',
  fieldBg = '#1a1a1a',
  borderStrong = '#2a2a2a',
  dark = false,
  onBack,
  vpnConnected = false,
}: Props) {
  const [preset, setPresetState] = useState(() => getDnsPreset())
  const [customInput, setCustomInput] = useState(() => getCustomDnsRaw())
  const [pending, setPending] = useState<DnsPreset | null>(null)

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
  }

  const options: DnsPreset[] = [...DNS_PRESETS]
  const beforeLabel = dnsApplyLabel(preset, customServers)
  const afterLabel = pending ? dnsApplyLabel(pending, customServers) : ''

  return (
    <div className="relative flex-1 p-4 overflow-y-auto w-full">
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
        Используйте рекомендуемый DNS или укажите свой.
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
        <div
          className="absolute inset-0 z-20 flex items-center justify-center px-6"
          style={{ background: 'rgba(0,0,0,0.46)' }}
          onClick={() => setPending(null)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="dns-apply-title"
            className="w-full max-w-[280px] px-6 pt-5 pb-4"
            style={{
              background: fieldBg,
              color: fg,
              borderRadius: 28,
              boxShadow: '0 8px 28px rgba(0,0,0,0.45)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div id="dns-apply-title" className="text-[22px] font-normal leading-7 mb-3">
              Применить?
            </div>
            <p className="text-sm leading-5 mb-6" style={{ color: muted }}>
              {beforeLabel} → {afterLabel}
              <br />
              <br />
              Переподключите VPN, чтобы применить.
            </p>
            <div className="flex justify-end items-center gap-2">
              <button
                type="button"
                onClick={() => setPending(null)}
                className="px-3 py-2 text-sm"
                style={{ color: `${fg}99` }}
              >
                Отмена
              </button>
              <button
                type="button"
                onClick={() => apply(pending)}
                className="px-4 py-1.5 text-sm font-medium"
                style={{ background: dark ? '#ffffff' : bg, color: dark ? '#111827' : fg, borderRadius: 20 }}
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

function dnsApplyLabel(preset: DnsPreset, customServers: string | null): string {
  if (preset.id !== 'custom') return preset.title
  return customServers ? `Свой DNS (${customServers})` : 'Свой DNS'
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
    <label
      className="flex items-center cursor-pointer"
      style={{ opacity: disabled ? 0.45 : 1, padding: '8px 0' }}
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
        disabled={disabled}
        onChange={() => !disabled && onSelect()}
        className="sr-only"
      />
      <div className="min-w-0" style={{ marginLeft: 8 }}>
        <div className="text-sm font-medium" style={{ color: fg }}>{option.title}</div>
        <div className="text-xs" style={{ color: muted }}>{option.subtitle}</div>
      </div>
    </label>
  )
}
