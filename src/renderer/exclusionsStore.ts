const EXCLUDED_KEY = 'pc_excluded_apps'
const WHITELIST_KEY = 'pc_exclusions_whitelist'
const BLACKLIST_KEY = 'pc_exclusions_blacklist'
const WHITELIST_APPS_KEY = 'pc_exclusions_whitelist_apps'
const DUAL_MIGRATED_KEY = 'pc_exclusions_dual_v1'
const SITE_RULES_KEY = 'pc_site_bypass_rules'

function parseIds(raw: string | null | undefined): Set<string> {
  return new Set((raw || '').split(',').map(s => s.trim()).filter(Boolean))
}

function joinIds(ids: Set<string> | string[]): string {
  return [...ids].join(',')
}

function ensureDualMigrated() {
  if (typeof localStorage === 'undefined') return
  if (localStorage.getItem(DUAL_MIGRATED_KEY) === '1') return
  const old = parseIds(localStorage.getItem(EXCLUDED_KEY))
  const mode = localStorage.getItem(WHITELIST_KEY) === '1'
  if (localStorage.getItem(BLACKLIST_KEY) == null) {
    localStorage.setItem(BLACKLIST_KEY, mode ? '' : joinIds(old))
  }
  if (localStorage.getItem(WHITELIST_APPS_KEY) == null) {
    localStorage.setItem(WHITELIST_APPS_KEY, mode ? joinIds(old) : '')
  }
  localStorage.setItem(DUAL_MIGRATED_KEY, '1')
}

export function isExclusionsWhitelist(): boolean {
  ensureDualMigrated()
  return localStorage.getItem(WHITELIST_KEY) === '1'
}

export function getBlacklistApps(): Set<string> {
  ensureDualMigrated()
  return parseIds(localStorage.getItem(BLACKLIST_KEY))
}

export function getWhitelistApps(): Set<string> {
  ensureDualMigrated()
  return parseIds(localStorage.getItem(WHITELIST_APPS_KEY))
}

export function getExcludedApps(): Set<string> {
  ensureDualMigrated()
  return isExclusionsWhitelist() ? getWhitelistApps() : getBlacklistApps()
}

function flushToMain(
  selected: Set<string>,
  apps: PcAppItem[] | undefined,
  whitelist: boolean,
  blacklist: Set<string>,
  whitelistApps: Set<string>,
) {
  try {
    const api = (window as any).electronAPI
    if (api?.saveAppExclusions) {
      const slim = (apps || []).map(a => ({
        id: a.id,
        name: a.name,
        exePath: a.exePath || null,
      }))
      void api.saveAppExclusions({
        selectedIds: [...selected],
        apps: slim,
        whitelist: !!whitelist,
        blacklistAppIds: [...blacklist],
        whitelistAppIds: [...whitelistApps],
      })
    }
  } catch {
    /* ignore */
  }
}

export function saveExcludedApps(
  ids: Set<string>,
  apps?: PcAppItem[],
  whitelist: boolean = isExclusionsWhitelist(),
) {
  ensureDualMigrated()
  localStorage.setItem(WHITELIST_KEY, whitelist ? '1' : '0')
  if (whitelist) {
    localStorage.setItem(WHITELIST_APPS_KEY, joinIds(ids))
  } else {
    localStorage.setItem(BLACKLIST_KEY, joinIds(ids))
  }
  localStorage.setItem(EXCLUDED_KEY, joinIds(ids))
  flushToMain(ids, apps, whitelist, getBlacklistApps(), getWhitelistApps())
}

/**
 * Смена ЧС↔БС: режим сохраняется, оба списка остаются.
 */
export function saveExceptionsMode(whitelist: boolean, apps?: PcAppItem[]) {
  ensureDualMigrated()
  localStorage.setItem(WHITELIST_KEY, whitelist ? '1' : '0')
  const active = whitelist ? getWhitelistApps() : getBlacklistApps()
  localStorage.setItem(EXCLUDED_KEY, joinIds(active))
  flushToMain(active, apps, whitelist, getBlacklistApps(), getWhitelistApps())
}

/** Сброс старого БС / «все отмечены» после смены id (ярлыки). */
export function resetStaleExclusions() {
  localStorage.removeItem(EXCLUDED_KEY)
  localStorage.setItem(WHITELIST_KEY, '0')
  localStorage.setItem(BLACKLIST_KEY, '')
  localStorage.setItem(WHITELIST_APPS_KEY, '')
  localStorage.setItem(DUAL_MIGRATED_KEY, '1')
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
