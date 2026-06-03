const EXCLUDED_KEY = 'pc_excluded_apps'
const WHITELIST_KEY = 'pc_exclusions_whitelist'

export function getExcludedApps(): Set<string> {
  const raw = localStorage.getItem(EXCLUDED_KEY) || ''
  return new Set(raw.split(',').map(s => s.trim()).filter(Boolean))
}

export function isExclusionsWhitelist(): boolean {
  return localStorage.getItem(WHITELIST_KEY) === '1'
}

export function saveExcludedApps(ids: Set<string>, whitelist: boolean) {
  localStorage.setItem(EXCLUDED_KEY, [...ids].join(','))
  localStorage.setItem(WHITELIST_KEY, whitelist ? '1' : '0')
}

export interface PcAppItem {
  id: string
  name: string
  installLocation?: string
  exePath?: string | null
  publisher?: string
  isSystem: boolean
  icon?: string | null
}
