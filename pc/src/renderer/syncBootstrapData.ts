import api, { getDeviceFingerprint } from './api'
import { pushLog } from './debugLog'
import {
  activeServerHashes,
  mapHashesResponse,
  saveHashItems,
  getSavedHashItems,
  type HashItem,
} from './hashItemsStore'
import { setTunnelApiBase, clearTunnelApiBase } from './tunnelApi'
/** Профиль и хеши через bootstrap WG (10.66.66.1), как Android syncLoginDataViaBootstrapTunnel. */
export async function syncLoginDataViaBootstrap(
  wgAddress?: string | null,
): Promise<{ profile: Record<string, unknown> | null; hashesOk: boolean }> {
  setTunnelApiBase(wgAddress)
  let profile: Record<string, unknown> | null = null
  let hashesOk = false
  try {
    const me = await api.get('/api/users/me')
    profile = me.data as Record<string, unknown>
    pushLog('Bootstrap', `profile OK vk=${profile?.vk_user_id ?? '?'}`)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Bootstrap', `profile FAIL: ${msg}`, 'W')
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
