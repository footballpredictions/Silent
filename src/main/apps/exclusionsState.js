/**
 * Состояние исключений на стороне main (для VPN-сессии).
 * Renderer синхронизирует через IPC save-app-exclusions.
 */
const fs = require('fs')
const path = require('path')
const { resolveBypassExePaths } = require('./exclusionsPolicy')

const DEFAULT_FILE_NAME = 'app-exclusions.json'

function defaultStatePath(userDataPath) {
  return path.join(userDataPath, DEFAULT_FILE_NAME)
}

/**
 * @param {object} opts
 * @param {string} opts.filePath
 * @param {string[]} opts.selectedIds
 * @param {Array<{id:string,name?:string,exePath?:string|null}>} opts.apps
 * @param {boolean} [opts.whitelist]
 */
function saveExclusionsState({ filePath, selectedIds, apps, whitelist = false }) {
  const resolved = resolveBypassExePaths({ selectedIds, apps, whitelist: !!whitelist })
  const payload = {
    version: 2,
    updatedAt: new Date().toISOString(),
    whitelist: !!whitelist,
    selectedIds: [...(selectedIds instanceof Set ? selectedIds : selectedIds || [])],
    apps: (apps || []).map(a => ({
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
      return { version: 2, whitelist: false, selectedIds: [], apps: [], entries: [], exePaths: [] }
    }
    const raw = JSON.parse(fs.readFileSync(filePath, 'utf8'))
    const selectedIds = Array.isArray(raw.selectedIds) ? raw.selectedIds : []
    const apps = Array.isArray(raw.apps) ? raw.apps : []
    const whitelist = !!raw.whitelist
    const entries = Array.isArray(raw.entries) ? raw.entries : []
    let exePaths = Array.isArray(raw.exePaths)
      ? raw.exePaths
      : entries.map(e => e.exePath).filter(Boolean)
    // Пересчёт с актуальным whitelist, если есть каталог apps
    if (apps.length) {
      exePaths = resolveBypassExePaths({ selectedIds, apps, whitelist }).exePaths
    }
    return {
      version: raw.version || 2,
      whitelist,
      selectedIds,
      apps,
      entries,
      exePaths,
      updatedAt: raw.updatedAt || null,
    }
  } catch {
    return { version: 2, whitelist: false, selectedIds: [], apps: [], entries: [], exePaths: [] }
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
