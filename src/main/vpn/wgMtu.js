/**
 * MTU из серверного профиля; без метаданных сохраняется прежняя политика слотов.
 * Общий модуль: Windows/Darwin/Linux + main tryApplyWg.
 */
const WG_MTU_DEFAULT = 1200
const WG_MTU_GAME = 1420
const GAME_SERVER_SLOT = 'server3'
const GAME_SERVER_IP = '78.17.74.27'

function resolveWgMtu(config) {
  const recommended = config?.wg_mtu
  if (Number.isInteger(recommended) && recommended >= 1200 && recommended <= 1420) return recommended
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
