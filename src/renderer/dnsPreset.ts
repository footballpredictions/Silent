/** DNS presets — только debug (меню «DNS»). Release: DNS из wireguard.js (Cloudflare+Yandex). */

export type DnsPresetId =
  | 'yandex'
  | 'cloudflare'
  | 'google'
  | 'quad9'
  | 'opendns'
  | 'adguard'
  | 'cleanbrowsing'
  | 'comodo'
  | 'verisign'
  | 'level3'
  | 'uncensoreddns'
  | 'alternate'

export interface DnsPreset {
  id: DnsPresetId
  title: string
  subtitle: string
  servers: string
}

export const DNS_PRESETS: DnsPreset[] = [
  { id: 'yandex', title: 'Яндекс', subtitle: '77.88.8.8 · как на сервере', servers: '77.88.8.8, 77.88.8.1' },
  { id: 'cloudflare', title: 'Cloudflare', subtitle: '1.1.1.1', servers: '1.1.1.1, 1.0.0.1' },
  { id: 'google', title: 'Google', subtitle: '8.8.8.8', servers: '8.8.8.8, 8.8.4.4' },
  { id: 'quad9', title: 'Quad9', subtitle: '9.9.9.9', servers: '9.9.9.9, 149.112.112.112' },
  { id: 'opendns', title: 'OpenDNS', subtitle: '208.67.222.222', servers: '208.67.222.222, 208.67.220.220' },
  { id: 'adguard', title: 'AdGuard DNS', subtitle: '94.140.14.14', servers: '94.140.14.14, 94.140.15.15' },
  { id: 'cleanbrowsing', title: 'CleanBrowsing', subtitle: '185.228.168.9', servers: '185.228.168.9, 185.228.169.9' },
  { id: 'comodo', title: 'Comodo Secure DNS', subtitle: '8.26.56.26', servers: '8.26.56.26, 8.20.247.20' },
  { id: 'verisign', title: 'Verisign', subtitle: '64.6.64.6', servers: '64.6.64.6, 64.6.65.6' },
  { id: 'level3', title: 'Level3', subtitle: '4.2.2.1', servers: '4.2.2.1, 4.2.2.2' },
  { id: 'uncensoreddns', title: 'UncensoredDNS', subtitle: '91.239.100.100', servers: '91.239.100.100, 89.233.43.71' },
  { id: 'alternate', title: 'Alternate DNS', subtitle: '76.76.19.19', servers: '76.76.19.19, 76.223.122.150' },
]

export const DNS_PRESET_DEFAULT = DNS_PRESETS[0]
const DNS_PRESET_KEY = 'silent_dns_preset'

export function dnsPresetFromId(id: string | null | undefined): DnsPreset {
  return DNS_PRESETS.find(p => p.id === id) || DNS_PRESET_DEFAULT
}

export function getDnsPreset(): DnsPreset {
  try {
    return dnsPresetFromId(localStorage.getItem(DNS_PRESET_KEY))
  } catch {
    return DNS_PRESET_DEFAULT
  }
}

export function setDnsPreset(preset: DnsPreset): void {
  localStorage.setItem(DNS_PRESET_KEY, preset.id)
}

/** Серверы для dns_override при debug-connect. */
export function getDnsOverrideServers(): string {
  return getDnsPreset().servers
}
