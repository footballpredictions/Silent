import api, { getDeviceFingerprint } from './api'
import { pushLog } from './debugLog'
import {
  activeServerHashes,
  mapHashesResponse,
  saveHashItems,
  getSavedHashItems,
  type HashItem,
} from './hashItemsStore'
import { enableTunnelApi, clearTunnelApiBase } from './tunnelApi'
import { saveCachedProfile } from './profileStore'
/** Профиль и хеши через публичный HTTPS (PC без блокировок). */
export async function syncLoginDataViaPublic(): Promise<{
  profile: Record<string, unknown> | null
  hashesOk: boolean
}> {
  clearTunnelApiBase()
  let profile: Record<string, unknown> | null = null
  let hashesOk = false
  for (let attempt = 1; attempt <= 2 && !profile; attempt++) {
    try {
      const me = await api.get('/api/users/me')
      profile = me.data as Record<string, unknown>
      saveCachedProfile(profile)
      pushLog('Bootstrap', `profile OK vk=${profile?.vk_user_id ?? '?'}`)
      break
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      pushLog('Bootstrap', `profile FAIL (${attempt}/2): ${msg}`, 'W')
      if (attempt < 2) await new Promise(r => setTimeout(r, 400))
    }
  }

  try {
    const hashesRes = await api.get('/api/vpn/hashes')
    const downloaded = mapHashesResponse(hashesRes.data)
    if (downloaded.length > 0) {
      saveHashItems(downloaded)
      hashesOk = true
      pushLog('Bootstrap', `hashes saved: ${activeServerHashes(downloaded).length} active`)
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Bootstrap', `hashes FAIL: ${msg}`, 'W')
  }

  let items: HashItem[] = getSavedHashItems()
  const active = activeServerHashes(items).length
  if (active < 4 && hashesOk) {
    try {
      const fp = getDeviceFingerprint()
      await api.post('/api/vpn/hashes/request-refresh', { device_fingerprint: fp })
      const again = await api.get('/api/vpn/hashes')
      const refreshed = mapHashesResponse(again.data)
      if (refreshed.length > items.length) {
        saveHashItems(refreshed)
        pushLog('Bootstrap', `hashes refresh: ${refreshed.length} items`)
      }
    } catch {
      /* AI refresh optional */
    }
  }

  clearTunnelApiBase()
  return { profile, hashesOk: hashesOk || activeServerHashes(getSavedHashItems()).length > 0 }
}

/** @deprecated PC: используйте syncLoginDataViaPublic */
export async function syncLoginDataViaBootstrap(
  _wgAddress?: string | null,
): Promise<{ profile: Record<string, unknown> | null; hashesOk: boolean }> {
  return syncLoginDataViaPublic()
}
