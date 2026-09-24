/**
 * MTU WireGuard: обычные слоты 1200; Сервер 3 (игры/Steam SDR) — 1420.
 * Общий модуль: Windows/Darwin/Linux + main tryApplyWg.
 */
const WG_MTU_DEFAULT = 1200
const WG_MTU_GAME = 1420
const GAME_SERVER_SLOT = 'server3'
const GAME_SERVER_IP = '78.17.74.27'

function resolveWgMtu(config) {
  const slot = String(config?.selected_server || '').trim().toLowerCase()
  const ip = String(config?.server_ip || '').trim()
  if (slot === GAME_SERVER_SLOT || ip === GAME_SERVER_IP) return WG_MTU_GAME
  return WG_MTU_DEFAULT
}

module.exports = {
  WG_MTU_DEFAULT,
  WG_MTU_GAME,
  GAME_SERVER_SLOT,
  GAME_SERVER_IP,
  resolveWgMtu,
}
