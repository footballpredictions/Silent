const EXCLUDED_KEY = 'pc_excluded_apps'
const WHITELIST_KEY = 'pc_exclusions_whitelist'
const BLACKLIST_KEY = 'pc_exclusions_blacklist'
const WHITELIST_APPS_KEY = 'pc_exclusions_whitelist_apps'
const DUAL_MIGRATED_KEY = 'pc_exclusions_dual_v1'
const SITE_RULES_KEY = 'pc_site_bypass_rules'
const SITE_WHITELIST_KEY = 'pc_site_whitelist'
const SITE_BLACKLIST_RULES_KEY = 'pc_site_blacklist_rules'
const SITE_WHITELIST_RULES_KEY = 'pc_site_whitelist_rules'

function readSiteRules(key: string): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '[]')
    return Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : []
  } catch { return [] }
}

function ensureSitesMigrated() {
  const mode = isSitesWhitelist()
  const legacy = readSiteRules(SITE_RULES_KEY)
  if (localStorage.getItem(SITE_BLACKLIST_RULES_KEY) == null) {
    localStorage.setItem(SITE_BLACKLIST_RULES_KEY, JSON.stringify(mode ? [] : legacy))
  }
  if (localStorage.getItem(SITE_WHITELIST_RULES_KEY) == null) {
    localStorage.setItem(SITE_WHITELIST_RULES_KEY, JSON.stringify(mode ? legacy : []))
  }
}

export function hydrateSiteBypassState(state: { rules: string[], whitelist: boolean, blacklistRules?: string[], whitelistRules?: string[] }) {
  const dual = Array.isArray(state.blacklistRules) || Array.isArray(state.whitelistRules)
  const black = dual ? state.blacklistRules || [] : state.whitelist ? [] : state.rules
  const white = dual ? state.whitelistRules || [] : state.whitelist ? state.rules : []
  localStorage.setItem(SITE_BLACKLIST_RULES_KEY, JSON.stringify(black))
  localStorage.setItem(SITE_WHITELIST_RULES_KEY, JSON.stringify(white))
  localStorage.setItem(SITE_RULES_KEY, JSON.stringify(state.whitelist ? white : black))
  localStorage.setItem(SITE_WHITELIST_KEY, state.whitelist ? '1' : '0')
}

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

export function getSiteBypassRules(whitelist = isSitesWhitelist()): string[] {
  ensureSitesMigrated()
  return readSiteRules(whitelist ? SITE_WHITELIST_RULES_KEY : SITE_BLACKLIST_RULES_KEY)
}

export function isSitesWhitelist(): boolean {
  return localStorage.getItem(SITE_WHITELIST_KEY) === '1'
}

export async function saveSiteBypassRules(rules: string[], whitelist = isSitesWhitelist()) {
  ensureSitesMigrated()
  const result = await (window as any).electronAPI?.saveSiteBypass?.({ rules, whitelist })
  if (result?.ok === false) throw new Error('Не удалось применить маршруты сайтов')
  hydrateSiteBypassState(result?.state || {
    whitelist, rules,
    blacklistRules: whitelist ? getSiteBypassRules(false) : rules,
    whitelistRules: whitelist ? rules : getSiteBypassRules(true),
  })
}

export async function saveSitesMode(whitelist: boolean) {
  ensureSitesMigrated()
  const result = await (window as any).electronAPI?.saveSiteBypass?.({ whitelist })
  if (result?.ok === false) throw new Error('Не удалось применить маршруты сайтов')
  hydrateSiteBypassState(result?.state || {
    whitelist, rules: getSiteBypassRules(whitelist),
    blacklistRules: getSiteBypassRules(false), whitelistRules: getSiteBypassRules(true),
  })
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
