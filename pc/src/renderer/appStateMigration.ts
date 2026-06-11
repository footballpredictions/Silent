import { getAppVersion } from './updateCheck'
import { clearCachedVpnConfig } from './vkConfig'
import { pushLog } from './debugLog'

const MIGRATED_VERSION_KEY = 'silent_app_migrated_version'

/** Одноразовая миграция после OTA — сброс только VPN-конфига (профиль не трогаем). */
export function runAppStateMigrationIfNeeded(): void {
  const current = getAppVersion()
  const last = localStorage.getItem(MIGRATED_VERSION_KEY) || ''
  if (last === current) return

  pushLog('App', `migrate ${last || '?'} → ${current}`)

  if (localStorage.getItem('silent_token')) {
    clearCachedVpnConfig()
  }

  localStorage.setItem(MIGRATED_VERSION_KEY, current)
}
