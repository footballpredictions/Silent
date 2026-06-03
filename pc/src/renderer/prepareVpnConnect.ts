import api from './api'
import { applyWorkerCount } from './hashChannelHelper'
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

  try {
    await api.post('/api/vpn/connect', {
      device_fingerprint: fingerprint,
      device_type: 'pc',
    })
  } catch {
    /* connect может вернуть 403 при лимите устройств — хеши всё равно пробуем */
  }

  let items: HashItem[] = getSavedHashItems()
  try {
    const hashesRes = await api.get('/api/vpn/hashes')
    const downloaded = mapHashesResponse(hashesRes.data)
    if (downloaded.length > 0) {
      saveHashItems(downloaded)
      items = downloaded
    }
    const active = activeServerHashes(items).length
    if (active < 4) {
      try {
        await api.post('/api/vpn/hashes/request-refresh', { device_fingerprint: fingerprint })
        const again = await api.get('/api/vpn/hashes')
        const refreshed = mapHashesResponse(again.data)
        if (refreshed.length > items.length) {
          saveHashItems(refreshed)
          items = refreshed
        }
      } catch {
        /* AI-агент может быть выключен */
      }
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Main', `hash sync: ${msg}`, 'W')
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
    const cfgRes = await api.get(`/api/vpn/config?fingerprint=${encodeURIComponent(fingerprint)}`)
    const fresh = cfgRes.data as VpnConfigPayload
    if (fresh.vk_hashes?.length) {
      merged = {
        ...merged,
        ...fresh,
        vk_hashes: fresh.vk_hashes,
        stream_count: fresh.stream_count,
      }
    }
  } catch {
    /* остаёмся на merged из register + hash sync */
  }

  const prepared = applyWorkerCount(merged)
  pushLog(
    'Main',
    `prepare n=${prepared.stream_count} hashes=${prepared.vk_hashes?.length ?? 0} stream_count_api=${merged.stream_count ?? '?'}`,
  )
  return prepared
}
