import api from './api'
import { applyWorkerCountForConnect } from './hashChannelHelper'
import {
  activeServerHashes,
  mapHashesResponse,
  saveHashItems,
  getSavedHashItems,
  type HashItem,
} from './hashItemsStore'
import type { VpnConfigPayload } from './vkConfig'
import { pushLog } from './debugLog'

/** Перед vpnConnect: слоты на сервере, свежие хеши, максимум потоков для libclient. */
export async function prepareVpnConnectConfig(
  config: VpnConfigPayload,
  fingerprint: string,
): Promise<VpnConfigPayload> {
  let merged = { ...config }

  const withTimeout = <T>(p: Promise<T>, ms: number): Promise<T | null> =>
    Promise.race([
      p,
      new Promise<null>(resolve => setTimeout(() => resolve(null), ms)),
    ])

  let items: HashItem[] = getSavedHashItems()
  const cachedActive = activeServerHashes(items).length
  const configHashes = (config.vk_hashes || []).map(h => h.trim()).filter(Boolean).length
  if (cachedActive >= 4 || configHashes >= 4) {
    const serverHashes = activeServerHashes(items).map(i => i.hash.trim()).filter(Boolean)
    if (serverHashes.length > 0) merged = { ...merged, vk_hashes: serverHashes }
    return applyWorkerCountForConnect(merged)
  }
  if (cachedActive < 4 && configHashes < 4) {
    const hashSyncDeadline = cachedActive > 0 ? 3_000 : 8_000
    try {
      const hashesRes = await withTimeout(api.get('/api/vpn/hashes'), hashSyncDeadline)
      if (!hashesRes) {
        pushLog('Main', 'hash sync: timeout before connect, using cache', 'W')
      } else {
        const downloaded = mapHashesResponse(hashesRes.data)
        if (downloaded.length > 0) {
          saveHashItems(downloaded)
          items = downloaded
        }
        const active = activeServerHashes(items).length
        if (active < 4) {
          try {
            await withTimeout(
              api.post('/api/vpn/hashes/request-refresh', { device_fingerprint: fingerprint }),
              5_000,
            )
            const again = await withTimeout(api.get('/api/vpn/hashes'), hashSyncDeadline)
            if (again) {
              const refreshed = mapHashesResponse(again.data)
              if (refreshed.length > items.length) {
                saveHashItems(refreshed)
                items = refreshed
              }
            }
          } catch {
            /* AI-агент может быть выключен */
          }
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      pushLog('Main', `hash sync: ${msg}`, 'W')
    }
  }

  const serverHashes = activeServerHashes(items).map(i => i.hash.trim()).filter(Boolean)
  if (serverHashes.length > 0) {
    merged = { ...merged, vk_hashes: serverHashes }
  } else if (merged.vk_hashes?.length) {
    merged = {
      ...merged,
      vk_hashes: merged.vk_hashes.map(h => h.trim()).filter(Boolean),
    }
  }

  try {
    const cfgRes = await withTimeout(
      api.get(`/api/vpn/config?fingerprint=${encodeURIComponent(fingerprint)}`),
      2_500,
    )
    if (cfgRes) {
      const fresh = cfgRes.data as VpnConfigPayload
      if (fresh.vk_hashes?.length) {
        merged = {
          ...merged,
          ...fresh,
          vk_hashes: fresh.vk_hashes,
          stream_count: fresh.stream_count,
        }
      }
    }
  } catch {
    /* остаёмся на merged из register + hash sync */
  }

  // Одна сессия wdtt с полным n из настроек (как Android). Без фонового upgrade — он рвал транспорт (0 воркеров при живом WG).
  const prepared = applyWorkerCountForConnect(merged)
  return prepared
}

let hashesTunnelSyncInFlight: Promise<boolean> | null = null

/** После поднятия WG: хеши через 10.66.66.1 (tunnel API), обновляет timestamp в меню. */
export async function syncHashesWhenTunnelUp(): Promise<boolean> {
  if (hashesTunnelSyncInFlight) return hashesTunnelSyncInFlight
  hashesTunnelSyncInFlight = (async () => {
    try {
      const hashesRes = await api.get('/api/vpn/hashes')
      const downloaded = mapHashesResponse(hashesRes.data)
      if (downloaded.length > 0) {
        saveHashItems(downloaded)
        pushLog('Main', `hashes sync via tunnel: ${downloaded.length} items`)
        return true
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      pushLog('Main', `hashes tunnel sync: ${msg}`, 'W')
    }
    return false
  })().finally(() => {
    hashesTunnelSyncInFlight = null
  })
  return hashesTunnelSyncInFlight
}
