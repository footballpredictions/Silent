import api, { getDeviceFingerprint } from './api'
import { pushLog } from './debugLog'
import {
  activeServerHashes,
  mapHashesResponse,
  saveHashItems,
  getSavedHashItems,
  type HashItem,
} from './hashItemsStore'
import { saveCachedProfile } from './profileStore'
import { prefetchOlcrtcConfig } from './bypassStore'

/**
 * Профиль + хеши + olcrtc-config при логине.
 * Вызывать ПОКА bootstrap/main tunnel ещё поднят (axios → main IPC → 10.66.66.1).
 */
export async function syncLoginDataViaTunnel(): Promise<{
  profile: Record<string, unknown> | null
  hashesOk: boolean
  olcrtcOk: boolean
}> {
  let profile: Record<string, unknown> | null = null
  let hashesOk = false
  let olcrtcOk = false

  try {
    const me = await api.get('/api/users/me', { timeout: 20_000 })
    profile = me.data as Record<string, unknown>
    saveCachedProfile(profile)
    pushLog('Bootstrap', `profile OK vk=${profile?.vk_user_id ?? '?'}`)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Bootstrap', `profile FAIL: ${msg}`, 'W')
  }

  try {
    const hashesRes = await api.get('/api/vpn/hashes', { timeout: 20_000 })
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

  // Опциональный refresh — не блокируем вход дольше 4с
  const items: HashItem[] = getSavedHashItems()
  const active = activeServerHashes(items).length
  if (active < 4 && hashesOk) {
    try {
      await Promise.race([
        (async () => {
          const fp = getDeviceFingerprint()
          await api.post('/api/vpn/hashes/request-refresh', { device_fingerprint: fp }, { timeout: 4_000 })
          const again = await api.get('/api/vpn/hashes', { timeout: 4_000 })
          const refreshed = mapHashesResponse(again.data)
          if (refreshed.length > items.length) {
            saveHashItems(refreshed)
            pushLog('Bootstrap', `hashes refresh: ${refreshed.length} items`)
          }
        })(),
        new Promise<void>(r => setTimeout(r, 4_000)),
      ])
    } catch {
      /* optional */
    }
  }

  try {
    const cfg = await prefetchOlcrtcConfig()
    olcrtcOk = !!cfg
    pushLog('Bootstrap', `olcrtc-config ${olcrtcOk ? 'OK' : 'FAIL'}`)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Bootstrap', `olcrtc-config FAIL: ${msg}`, 'W')
  }

  return {
    profile,
    hashesOk: hashesOk || activeServerHashes(getSavedHashItems()).length > 0,
    olcrtcOk,
  }
}

/** @deprecated — используйте syncLoginDataViaTunnel при bootstrap */
export async function syncLoginDataViaPublic(): Promise<{
  profile: Record<string, unknown> | null
  hashesOk: boolean
  olcrtcOk: boolean
}> {
  return syncLoginDataViaTunnel()
}

/** @deprecated */
export async function syncLoginDataViaBootstrap(
  _wgAddress?: string | null,
): Promise<{ profile: Record<string, unknown> | null; hashesOk: boolean; olcrtcOk: boolean }> {
  return syncLoginDataViaTunnel()
}
