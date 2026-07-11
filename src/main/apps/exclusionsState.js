/**
 * Состояние исключений на стороне main (для VPN-сессии).
 * Renderer синхронизирует через IPC save-app-exclusions.
 */
const fs = require('fs')
const path = require('path')
const { resolveExcludedExePaths } = require('./exclusionsPolicy')

const DEFAULT_FILE_NAME = 'app-exclusions.json'

function defaultStatePath(userDataPath) {
  return path.join(userDataPath, DEFAULT_FILE_NAME)
}

/**
 * @param {object} opts
 * @param {string} opts.filePath
 * @param {string[]} opts.selectedIds
 * @param {Array<{id:string,name?:string,exePath?:string|null}>} opts.apps
 */
function saveExclusionsState({ filePath, selectedIds, apps }) {
  const resolved = resolveExcludedExePaths(selectedIds, apps)
  const payload = {
    version: 1,
    updatedAt: new Date().toISOString(),
    selectedIds: [...(selectedIds instanceof Set ? selectedIds : selectedIds || [])],
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
      return { version: 1, selectedIds: [], entries: [], exePaths: [] }
    }
    const raw = JSON.parse(fs.readFileSync(filePath, 'utf8'))
    const selectedIds = Array.isArray(raw.selectedIds) ? raw.selectedIds : []
    const entries = Array.isArray(raw.entries) ? raw.entries : []
    const exePaths = Array.isArray(raw.exePaths)
      ? raw.exePaths
      : entries.map(e => e.exePath).filter(Boolean)
    return {
      version: raw.version || 1,
      selectedIds,
      entries,
      exePaths,
      updatedAt: raw.updatedAt || null,
    }
  } catch {
    return { version: 1, selectedIds: [], entries: [], exePaths: [] }
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
