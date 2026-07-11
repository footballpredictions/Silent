const EXCLUDED_KEY = 'pc_excluded_apps'
const WHITELIST_KEY = 'pc_exclusions_whitelist'

export function getExcludedApps(): Set<string> {
  const raw = localStorage.getItem(EXCLUDED_KEY) || ''
  return new Set(raw.split(',').map(s => s.trim()).filter(Boolean))
}

export function saveExcludedApps(ids: Set<string>, apps?: PcAppItem[]) {
  localStorage.setItem(EXCLUDED_KEY, [...ids].join(','))
  localStorage.setItem(WHITELIST_KEY, '0')
  try {
    const api = (window as any).electronAPI
    if (api?.saveAppExclusions) {
      const slim = (apps || []).map(a => ({
        id: a.id,
        name: a.name,
        exePath: a.exePath || null,
      }))
      void api.saveAppExclusions({ selectedIds: [...ids], apps: slim })
    }
  } catch {
    /* ignore */
  }
}

/** Сброс старого БС / «все отмечены» после смены id (ярлыки). */
export function resetStaleExclusions() {
  localStorage.removeItem(EXCLUDED_KEY)
  localStorage.setItem(WHITELIST_KEY, '0')
}

export interface PcAppItem {
  id: string
  name: string
  installLocation?: string
  exePath?: string | null
  lnkPath?: string | null
  publisher?: string
  isSystem: boolean
  icon?: string | null
}
