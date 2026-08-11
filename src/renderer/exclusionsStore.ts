const EXCLUDED_KEY = 'pc_excluded_apps'
const WHITELIST_KEY = 'pc_exclusions_whitelist'
const SITE_RULES_KEY = 'pc_site_bypass_rules'

export function getExcludedApps(): Set<string> {
  const raw = localStorage.getItem(EXCLUDED_KEY) || ''
  return new Set(raw.split(',').map(s => s.trim()).filter(Boolean))
}

export function isExclusionsWhitelist(): boolean {
  return localStorage.getItem(WHITELIST_KEY) === '1'
}

export function saveExcludedApps(
  ids: Set<string>,
  apps?: PcAppItem[],
  whitelist: boolean = false,
) {
  localStorage.setItem(EXCLUDED_KEY, [...ids].join(','))
  localStorage.setItem(WHITELIST_KEY, whitelist ? '1' : '0')
  try {
    const api = (window as any).electronAPI
    if (api?.saveAppExclusions) {
      const slim = (apps || []).map(a => ({
        id: a.id,
        name: a.name,
        exePath: a.exePath || null,
      }))
      void api.saveAppExclusions({
        selectedIds: [...ids],
        apps: slim,
        whitelist: !!whitelist,
      })
    }
  } catch {
    /* ignore */
  }
}

/**
 * Смена ЧС↔БС.
 * ЧС — пустой выбор; БС — все приложения уже отмечены (пользователь снимет лишнее).
 */
export function saveExceptionsMode(whitelist: boolean, apps?: PcAppItem[]) {
  if (whitelist) {
    const all = new Set((apps || []).map(a => a.id))
    saveExcludedApps(all, apps, true)
  } else {
    saveExcludedApps(new Set(), apps, false)
  }
}

/** Сброс старого БС / «все отмечены» после смены id (ярлыки). */
export function resetStaleExclusions() {
  localStorage.removeItem(EXCLUDED_KEY)
  localStorage.setItem(WHITELIST_KEY, '0')
}

export function getSiteBypassRules(): string[] {
  try {
    const raw = localStorage.getItem(SITE_RULES_KEY) || ''
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : []
  } catch {
    return []
  }
}

export function saveSiteBypassRules(rules: string[]) {
  localStorage.setItem(SITE_RULES_KEY, JSON.stringify(rules))
  try {
    const api = (window as any).electronAPI
    if (api?.saveSiteBypass) {
      void api.saveSiteBypass({ rules })
    }
  } catch {
    /* ignore */
  }
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
