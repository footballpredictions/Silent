/**
 * Чистая политика исключений приложений (без Electron / VPN).
 * ЧС: выбранные id → пути .exe мимо туннеля.
 * БС: все известные exe кроме выбранных → мимо туннеля.
 */

function normalizePath(p) {
  return String(p || '')
    .trim()
    .replace(/^["']|["']$/g, '')
    .replace(/\//g, '\\')
    .toLowerCase()
}

/**
 * @param {Set<string>|string[]} selectedIds
 * @param {Array<{ id: string, name?: string, exePath?: string|null }>} apps
 * @returns {{ exePaths: string[], entries: Array<{ id: string, name: string, exePath: string }> }}
 */
function resolveExcludedExePaths(selectedIds, apps) {
  const ids = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || [])
  const byId = new Map((apps || []).map(a => [a.id, a]))
  const seen = new Set()
  const entries = []

  for (const id of ids) {
    const app = byId.get(id)
    if (!app) continue
    const exe = String(app.exePath || '').trim()
    if (!exe || !/\.exe$/i.test(exe)) continue
    const key = normalizePath(exe)
    if (!key || seen.has(key)) continue
    seen.add(key)
    entries.push({
      id: app.id,
      name: String(app.name || '').trim() || id,
      exePath: exe,
    })
  }

  entries.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return {
    exePaths: entries.map(e => e.exePath),
    entries,
  }
}

/**
 * Пути .exe, которые должны идти мимо VPN.
 * @param {{ selectedIds: string[], apps: Array, whitelist?: boolean }} opts
 */
function resolveBypassExePaths({ selectedIds, apps, whitelist = false }) {
  const list = apps || []
  if (!whitelist) {
    return resolveExcludedExePaths(selectedIds, list)
  }
  const ids = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || [])
  // Пустой БС = весь трафик в VPN, а не «все приложения мимо».
  if (ids.size === 0) {
    return { exePaths: [], entries: [] }
  }
  // БС: мимо VPN всё, кроме выбранных (и без Silent). Сравниваем по exe-path — id могут дублировать один .exe.
  const keepIds = new Set(selectedIds || [])
  const keepExe = new Set()
  for (const app of list) {
    if (!keepIds.has(app.id)) continue
    const exe = String(app.exePath || '').trim()
    if (exe && /\.exe$/i.test(exe)) keepExe.add(normalizePath(exe))
  }
  const seen = new Set()
  const entries = []
  for (const app of list) {
    const exe = String(app.exePath || '').trim()
    if (!exe || !/\.exe$/i.test(exe)) continue
    const key = normalizePath(exe)
    if (!key || keepExe.has(key) || seen.has(key)) continue
    const name = String(app.name || '')
    if (/silent\s*vpn/i.test(name) || /silentvpn/i.test(key)) continue
    seen.add(key)
    entries.push({
      id: app.id,
      name: name.trim() || app.id,
      exePath: exe,
    })
  }
  entries.sort((a, b) => a.name.localeCompare(b.name, 'ru'))
  return {
    exePaths: entries.map(e => e.exePath),
    entries,
  }
}

/** Проверка: процесс с данным путём должен быть вне VPN. */
function isProcessExcluded(processPath, excludedExePaths) {
  const needle = normalizePath(processPath)
  if (!needle) return false
  const list = (excludedExePaths || []).map(normalizePath).filter(Boolean)
  if (list.includes(needle)) return true
  const base = needle.split('\\').pop()
  if (!base) return false
  return list.some(p => p.split('\\').pop() === base)
}

module.exports = {
  normalizePath,
  resolveExcludedExePaths,
  resolveBypassExePaths,
  isProcessExcluded,
}
