/**
 * DNS туннеля: пресеты + свой ввод (меню «DNS»).
 * `server` ничего не подменяет — DNS приходит с сервера в `wg_dns`
 * (в том числе `10.66.66.1`, когда включён фильтр угроз).
 */

export type DnsPresetId =
  | 'server'
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
  | 'custom'

export interface DnsPreset {
  id: DnsPresetId
  title: string
  subtitle: string
  servers: string
}

/** Выбираемые пресеты; свой ввод — отдельной секцией. */
export const DNS_PRESETS: DnsPreset[] = [
  { id: 'yandex', title: 'Яндекс (как на сервере)', subtitle: '77.88.8.8 · рекомендуется', servers: '77.88.8.8, 77.88.8.1' },
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

export const DNS_PRESET_CUSTOM: DnsPreset = {
  id: 'custom',
  title: 'Свой DNS',
  subtitle: 'до 3 адресов через запятую',
  servers: '',
}

export const DNS_PRESET_DEFAULT = DNS_PRESETS[0]
/** Когда сервер не прислал wg_dns и подменять нечем. */
export const DNS_FALLBACK_SERVERS = '77.88.8.8, 77.88.8.1'
export const MAX_CUSTOM_SERVERS = 3

const DNS_PRESET_KEY = 'silent_dns_preset'
const DNS_CUSTOM_KEY = 'silent_dns_custom'

const IPV4 = /^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$/

function isIpv6(token: string): boolean {
  if (!token.includes(':')) return false
  if ((token.match(/:/g) || []).length < 2) return false
  if (token.length > 45) return false
  return /^[0-9a-fA-F:.]+$/.test(token)
}

export function isValidDnsServer(token: string): boolean {
  return IPV4.test(token) || isIpv6(token)
}

/** Ввод пользователя → нормализованный список; null, если корректных адресов нет. */
export function sanitizeCustomServers(raw: string | null | undefined): string | null {
  const tokens = String(raw || '')
    .split(/[,;\s]+/)
    .map(s => s.trim())
    .filter(s => s.length > 0 && isValidDnsServer(s))
  const unique = Array.from(new Set(tokens)).slice(0, MAX_CUSTOM_SERVERS)
  return unique.length ? unique.join(', ') : null
}

export function dnsPresetFromId(id: string | null | undefined): DnsPreset {
  if (id === 'custom') return DNS_PRESET_CUSTOM
  if (id === 'server') return DNS_PRESETS[0]
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
  try {
    localStorage.setItem(DNS_PRESET_KEY, preset.id)
  } catch {
    /* localStorage недоступен — настройка не сохранится */
  }
}

export function getCustomDnsRaw(): string {
  try {
    return localStorage.getItem(DNS_CUSTOM_KEY) || ''
  } catch {
    return ''
  }
}

/** Сохраняет нормализованный свой DNS; возвращает то, что сохранено. */
export function setCustomDns(raw: string): string | null {
  const servers = sanitizeCustomServers(raw)
  try {
    localStorage.setItem(DNS_CUSTOM_KEY, servers || '')
  } catch {
    /* localStorage недоступен */
  }
  return servers
}

/** Серверы для `dns_override`; пустая строка — оставить DNS сервера. */
export function getDnsOverrideServers(): string {
  const preset = getDnsPreset()
  if (preset.id === 'custom') return sanitizeCustomServers(getCustomDnsRaw()) || ''
  return preset.servers
}

/** Короткая подпись для пункта меню. */
export function dnsMenuLabel(): string {
  const preset = getDnsPreset()
  if (preset.id !== 'custom') return preset.title
  return sanitizeCustomServers(getCustomDnsRaw()) || 'не задан'
}

/** Строка для диалога подтверждения и лога. */
export function dnsDescription(): string {
  const preset = getDnsPreset()
  if (preset.id === 'custom') {
    const servers = sanitizeCustomServers(getCustomDnsRaw())
    return servers ? `Свой: ${servers}` : 'Свой DNS (не задан)'
  }
  return `${preset.title} (${preset.servers})`
}
