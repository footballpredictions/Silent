/**
 * Применение исключений приложений к VPN-сессии.
 *
 * WireGuard for Windows не умеет excludeApplications (в отличие от Android VpnService).
 * Реальный обход: монитор remote IP выбранных процессов → host-route через физ. шлюз
 * (см. appExclusionBypass.js).
 */
const { isProcessExcluded } = require('./exclusionsPolicy')
const {
  startAppExclusionBypass,
  stopAppExclusionBypass,
  refreshAppExclusionBypassAfterTunnel,
} = require('./appExclusionBypass')

let activeExcludedExePaths = []

function setActiveExcludedExePaths(exePaths) {
  activeExcludedExePaths = [...new Set((exePaths || []).filter(Boolean))]
  return activeExcludedExePaths
}

function getActiveExcludedExePaths() {
  return [...activeExcludedExePaths]
}

async function clearActiveExcludedExePaths(send) {
  activeExcludedExePaths = []
  await stopAppExclusionBypass(send)
}

/**
 * @param {string[]} exePaths
 * @param {(line: string) => void} [send]
 * @param {{ enableBypass?: boolean }} [options]
 * @returns {{ applied: string[], missing: string[] }}
 */
function applyAppExclusionsForSession(exePaths, send, options = {}) {
  const list = setActiveExcludedExePaths(exePaths)
  if (!list.length) {
    send?.('[Apps] исключения: нет выбранных .exe')
    void stopAppExclusionBypass(send)
    return { applied: [], missing: [] }
  }
  send?.(`[Apps] исключения сессии: ${list.length} — ${list.map(p => p.split(/[/\\]/).pop()).join(', ')}`)
  if (options.enableBypass !== false) {
    startAppExclusionBypass(list, send)
  }
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
  refreshAppExclusionBypassAfterTunnel,
}
