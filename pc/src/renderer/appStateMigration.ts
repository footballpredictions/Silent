import { getAppVersion } from './updateCheck'
import { clearCachedVpnConfig, getCachedVpnConfig } from './vkConfig'
import { pushLog } from './debugLog'

const MIGRATED_VERSION_KEY = 'silent_app_migrated_version'

function cachedConfigHasWgKeys(): boolean {
  const cfg = getCachedVpnConfig()
  return !!cfg?.wg_private_key?.trim() && !!cfg?.server_public_key?.trim()
}

/** Одноразовая миграция после OTA — сброс только битого VPN-кеша (валидные ключи сохраняем). */
export function runAppStateMigrationIfNeeded(): void {
  const current = getAppVersion()
  const last = localStorage.getItem(MIGRATED_VERSION_KEY) || ''
  if (last === current) return

  pushLog('App', `migrate ${last || '?'} → ${current}`)

  if (localStorage.getItem('silent_token') && !cachedConfigHasWgKeys()) {
    clearCachedVpnConfig()
  }

  localStorage.setItem(MIGRATED_VERSION_KEY, current)
}
