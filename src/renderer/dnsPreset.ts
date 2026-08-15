/**
 * DNS туннеля: «Как на сервере» + свой ввод (меню «DNS»).
 * `server` ничего не подменяет — DNS приходит с сервера в `wg_dns`
 * (в том числе `10.66.66.1`, когда включён фильтр угроз).
 */

export type DnsPresetId = 'server' | 'custom'

export interface DnsPreset {
  id: DnsPresetId
  title: string
  subtitle: string
  servers: string
}

/** Выбираемые пресеты; свой ввод — отдельной секцией. */
export const DNS_PRESETS: DnsPreset[] = [
  { id: 'server', title: 'Как на сервере', subtitle: 'Рекомендуется', servers: '' },
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

/**
 * Публичные пресеты 1.0.161 (`yandex`, `cloudflare`, …) сворачиваем в `server`:
 * принудительный публичный DNS ломал резолв в туннеле (YouTube на VK-обходе).
 */
export function dnsPresetFromId(id: string | null | undefined): DnsPreset {
  return id === 'custom' ? DNS_PRESET_CUSTOM : DNS_PRESET_DEFAULT
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
  // «Как на сервере»: не подменяем DNS, оставляем серверный wg_dns.
  return ''
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
  return DNS_PRESET_DEFAULT.title
}
