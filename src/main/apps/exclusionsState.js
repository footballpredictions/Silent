/**
 * Состояние исключений на стороне main (для VPN-сессии).
 * Renderer синхронизирует через IPC save-app-exclusions.
 * Два независимых списка + режим; смена режима не затирает другой список.
 */
const fs = require('fs')
const path = require('path')
const { resolveBypassExePaths } = require('./exclusionsPolicy')
const {
  hydrateExclusions,
  applySave,
  activeIds,
} = require('./exclusionsPersist')

const DEFAULT_FILE_NAME = 'app-exclusions.json'

function defaultStatePath(userDataPath) {
  return path.join(userDataPath, DEFAULT_FILE_NAME)
}

function emptyState() {
  return {
    version: 3,
    whitelist: false,
    appBypassMode: 'blacklist',
    selectedIds: [],
    blacklistAppIds: [],
    whitelistAppIds: [],
    apps: [],
    entries: [],
    exePaths: [],
  }
}

function toPublicState(hydrated, apps, entries, exePaths, updatedAt) {
  const selected = activeIds(hydrated)
  return {
    version: 3,
    whitelist: !!hydrated.whitelist,
    appBypassMode: hydrated.appBypassMode,
    selectedIds: selected,
    blacklistAppIds: [...hydrated.blacklistAppIds],
    whitelistAppIds: [...hydrated.whitelistAppIds],
    apps: apps || [],
    entries: entries || [],
    exePaths: exePaths || [],
    updatedAt: updatedAt || null,
  }
}

function resolveForState(hydrated, apps) {
  const selected = activeIds(hydrated)
  return resolveBypassExePaths({
    selectedIds: selected,
    apps,
    whitelist: !!hydrated.whitelist,
  })
}

/**
 * @param {object} opts
 * @param {string} opts.filePath
 * @param {string[]} [opts.selectedIds]
 * @param {Array<{id:string,name?:string,exePath?:string|null}>} opts.apps
 * @param {boolean} [opts.whitelist]
 * @param {string[]} [opts.blacklistAppIds]
 * @param {string[]} [opts.whitelistAppIds]
 */
function saveExclusionsState({
  filePath,
  selectedIds,
  apps,
  whitelist = false,
  blacklistAppIds,
  whitelistAppIds,
}) {
  const prev = loadExclusionsState(filePath)
  const next = applySave(prev, {
    selectedIds,
    whitelist,
    blacklistAppIds,
    whitelistAppIds,
  })
  const list = apps || prev.apps || []
  const resolved = resolveForState(next, list)
  const payload = {
    version: 3,
    updatedAt: new Date().toISOString(),
    whitelist: !!next.whitelist,
    appBypassMode: next.appBypassMode,
    selectedIds: activeIds(next),
    blacklistAppIds: [...next.blacklistAppIds],
    whitelistAppIds: [...next.whitelistAppIds],
    apps: list.map(a => ({
      id: a.id,
      name: a.name || '',
      exePath: a.exePath || null,
    })),
    entries: resolved.entries,
    exePaths: resolved.exePaths,
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), 'utf8')
  return payload
}

function loadExclusionsState(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      return emptyState()
    }
    const raw = JSON.parse(fs.readFileSync(filePath, 'utf8'))
    const apps = Array.isArray(raw.apps) ? raw.apps : []
    const hydrated = hydrateExclusions({
      selectedIds: Array.isArray(raw.selectedIds) ? raw.selectedIds : [],
      whitelist: !!raw.whitelist,
      blacklistAppIds: Array.isArray(raw.blacklistAppIds) ? raw.blacklistAppIds : (raw.blacklistAppIds == null ? null : []),
      whitelistAppIds: Array.isArray(raw.whitelistAppIds) ? raw.whitelistAppIds : (raw.whitelistAppIds == null ? null : []),
    })
    const entries = Array.isArray(raw.entries) ? raw.entries : []
    let exePaths = Array.isArray(raw.exePaths)
      ? raw.exePaths
      : entries.map(e => e.exePath).filter(Boolean)
    if (apps.length) {
      exePaths = resolveForState(hydrated, apps).exePaths
    }
    return toPublicState(hydrated, apps, entries, exePaths, raw.updatedAt || null)
  } catch {
    return emptyState()
  }
}

/** Пути .exe для текущей VPN-сессии (из сохранённого состояния). */
function getExcludedExePathsForVpn(filePath) {
  return loadExclusionsState(filePath).exePaths.filter(p => typeof p === 'string' && /\.exe$/i.test(p))
}

module.exports = {
  DEFAULT_FILE_NAME,
  defaultStatePath,
  saveExclusionsState,
  loadExclusionsState,
  getExcludedExePathsForVpn,
}
