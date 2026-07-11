/**
 * Применение исключений приложений к VPN-сессии.
 *
 * WireGuard for Windows не умеет excludeApplications (в отличие от Android VpnService).
 * Здесь фиксируем план исключений для сессии и проверяем покрытие выбранных exe.
 * Полноценный process-split на Windows требует WFP-драйвер (отдельная задача).
 */
const { isProcessExcluded } = require('./exclusionsPolicy')

let activeExcludedExePaths = []

function setActiveExcludedExePaths(exePaths) {
  activeExcludedExePaths = [...new Set((exePaths || []).filter(Boolean))]
  return activeExcludedExePaths
}

function getActiveExcludedExePaths() {
  return [...activeExcludedExePaths]
}

function clearActiveExcludedExePaths() {
  activeExcludedExePaths = []
}

/**
 * @param {string[]} exePaths
 * @param {(line: string) => void} [send]
 * @returns {{ applied: string[], missing: string[] }}
 */
function applyAppExclusionsForSession(exePaths, send) {
  const list = setActiveExcludedExePaths(exePaths)
  if (!list.length) {
    send?.('[Apps] исключения: нет выбранных .exe')
    return { applied: [], missing: [] }
  }
  send?.(`[Apps] исключения сессии: ${list.length} — ${list.map(p => p.split(/[/\\]/).pop()).join(', ')}`)
  // План зафиксирован; сетевой bypass per-process — следующий этап (WFP).
  return { applied: list, missing: [] }
}

/** Юнит/авто: выбранный exe считается исключённым в активной сессии. */
function assertExeExcludedInSession(exePath) {
  return isProcessExcluded(exePath, activeExcludedExePaths)
}

module.exports = {
  setActiveExcludedExePaths,
  getActiveExcludedExePaths,
  clearActiveExcludedExePaths,
  applyAppExclusionsForSession,
  assertExeExcludedInSession,
}
