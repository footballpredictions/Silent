import {
  getVkCredStrategy,
  setVkCredStrategy,
  VK_CRED_AUTO,
  VK_CRED_MANUAL,
  VK_CRED_VKCALLS,
  vkCredStrategyLabel,
} from './vkCredStore'
import { getPublicApiBaseUrl } from './tunnelApi'
import { getStableDeviceFingerprint } from './api'
import { getDnsOverrideServers } from './dnsPreset'
import { isDebugBuild } from './debugBuild'

const FAMILY_KEY = 'bypass_family'
const OLCRTC_PROVIDER_KEY = 'olcrtc_provider'
/** v12: dual-cache telemost / wbstream (не затирают друг друга). */
const OLCRTC_CACHE_KEY_LEGACY = 'olcrtc_config_cache_v11'
function olcrtcCacheKey(provider: string = getOlcrtcProvider()): string {
  const p =
    provider === OLCRTC_WBSTREAM || provider === OLCRTC_TELEMOST
      ? provider
      : OLCRTC_TELEMOST
  return `olcrtc_config_cache_v12_${p}`
}

export const BYPASS_FAMILY_WDTT = 'wdtt'
export const BYPASS_FAMILY_OLCRTC = 'olcrtc'
export const BYPASS_FAMILY_OLCRTC2 = 'olcrtc2'

export const OLCRTC_WBSTREAM = 'wbstream'
export const OLCRTC_TELEMOST = 'telemost'
/** @deprecated Jitsi убран — миграция старых prefs → telemost */
export const OLCRTC_JITSI = 'jitsi'

export {
  getVkCredStrategy,
  setVkCredStrategy,
  VK_CRED_AUTO,
  VK_CRED_MANUAL,
  VK_CRED_VKCALLS,
  vkCredStrategyLabel,
}

export function getBypassFamily(): string {
  if (!isDebugBuild) return BYPASS_FAMILY_WDTT
  try {
    const v = localStorage.getItem(FAMILY_KEY)
    if (v === BYPASS_FAMILY_OLCRTC2) return BYPASS_FAMILY_OLCRTC2
    // старый olcrtc v1 больше не поддерживается → WDTT
    if (v === BYPASS_FAMILY_OLCRTC) {
      localStorage.setItem(FAMILY_KEY, BYPASS_FAMILY_WDTT)
    }
  } catch { /* ignore */ }
  return BYPASS_FAMILY_WDTT
}

export function setBypassFamily(family: string) {
  if (!isDebugBuild) {
    localStorage.setItem(FAMILY_KEY, BYPASS_FAMILY_WDTT)
    return
  }
  if (family === BYPASS_FAMILY_OLCRTC || family === BYPASS_FAMILY_OLCRTC2) {
    localStorage.setItem(FAMILY_KEY, BYPASS_FAMILY_OLCRTC2)
    return
  }
  localStorage.setItem(FAMILY_KEY, BYPASS_FAMILY_WDTT)
}

export function getOlcrtcProvider(): string {
  try {
    const v = localStorage.getItem(OLCRTC_PROVIDER_KEY)
    if (v === OLCRTC_WBSTREAM || v === OLCRTC_TELEMOST) return v
    if (v === OLCRTC_JITSI) return OLCRTC_TELEMOST
  } catch { /* ignore */ }
  return OLCRTC_TELEMOST
}

export function setOlcrtcProvider(provider: string) {
  const normalized =
    provider === OLCRTC_WBSTREAM || provider === OLCRTC_TELEMOST
      ? provider
      : OLCRTC_TELEMOST
  localStorage.setItem(OLCRTC_PROVIDER_KEY, normalized)
}

export function isOlcrtcBypass(): boolean {
  return isDebugBuild && getBypassFamily() === BYPASS_FAMILY_OLCRTC2
}

export function olcrtcProviderLabel(provider: string = getOlcrtcProvider()): string {
  switch (provider) {
    case OLCRTC_WBSTREAM: return 'WB Stream'
    case OLCRTC_TELEMOST: return 'Яндекс Телемост'
    default: return 'Яндекс Телемост'
  }
}

export function bypassFamilyLabel(family: string = getBypassFamily()): string {
  if (family === BYPASS_FAMILY_OLCRTC2 || family === BYPASS_FAMILY_OLCRTC) {
    return `olcrtc / ${olcrtcProviderLabel()}`
  }
  return 'VK'
}

export type OlcrtcPublicConfig = {
  enabled: boolean
  crypto_key: string
  socks_host?: string
  socks_port?: number
  assigned_slot?: string
  device_type?: string
  pool_denied?: boolean
  pool_denied_detail?: string
  providers: Record<
    string,
    {
      enabled: boolean
      room: string
      transport: string
      room_slot_id?: string
      room_db_id?: string
      rooms_count?: number
      denied?: boolean
      /** WB Stream: JWT аккаунта (не guest) — guest getToken → 403 */
      auth_token?: string
    }
  >
}

let heartbeatTimer: ReturnType<typeof setInterval> | null = null

export async function sendOlcrtcHeartbeat(online: boolean = true): Promise<void> {
  try {
    const cfg = readOlcrtcCache()
    const prov = getOlcrtcProvider()
    const roomDbId = cfg?.providers?.[prov]?.room_db_id
    if (!roomDbId) {
      if (online) {
        try {
          const { pushLog } = await import('./debugLog')
          pushLog('olcrtc', 'heartbeat skip: нет room_db_id в кеше', 'W')
        } catch { /* ignore */ }
      }
      return
    }
    const fp = getStableDeviceFingerprint()
    const body = {
      room_db_id: roomDbId,
      fingerprint: fp,
      provider: prov,
      device_type: 'pc',
      online,
    }

    const electron = (window as unknown as {
      electronAPI?: {
        tunnelApiRequest?: (p: {
          method: string
          path: string
          body?: unknown
          timeout?: number
        }) => Promise<{ status: number; data: unknown }>
      }
    }).electronAPI

    // Как /olcrtc-config: через main IPC (при VPN bypass / иначе public).
    if (electron?.tunnelApiRequest) {
      const res = await electron.tunnelApiRequest({
        method: 'POST',
        path: '/api/vpn/olcrtc2-heartbeat',
        body,
        timeout: 15_000,
      })
      if (online && (res?.status < 200 || res?.status >= 300)) {
        try {
          const { pushLog } = await import('./debugLog')
          pushLog('olcrtc', `heartbeat HTTP ${res?.status}`, 'W')
        } catch { /* ignore */ }
      }
      return
    }

    const base = getPublicApiBaseUrl().replace(/\/$/, '')
    const res = await fetch(`${base}/api/vpn/olcrtc2-heartbeat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    })
    if (online && !res.ok) {
      try {
        const { pushLog } = await import('./debugLog')
        pushLog('olcrtc', `heartbeat HTTP ${res.status}`, 'W')
      } catch { /* ignore */ }
    }
  } catch (e) {
    if (online) {
      try {
        const { pushLog } = await import('./debugLog')
        pushLog('olcrtc', `heartbeat fail: ${e instanceof Error ? e.message : e}`, 'W')
      } catch { /* ignore */ }
    }
  }
}

/** Запуск heartbeat. НЕ делает leave — иначе sticky снимается и agent рвёт комнату. */
export function startOlcrtcHeartbeatLoop(): void {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  void sendOlcrtcHeartbeat(true)
  // Сервер HEARTBEAT_STALE_SEC=300 — интервал с запасом.
  heartbeatTimer = setInterval(() => {
    void sendOlcrtcHeartbeat(true)
  }, 30_000)
}

/** Только остановить таймер. Leave — отдельно при disconnect. */
export function stopOlcrtcHeartbeatLoop(opts?: { leave?: boolean }): void {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  if (opts?.leave) {
    void leaveOlcrtcRoom()
  }
}

/** Leave текущего провайдера: sticky offline, dual-cache соседнего не трогаем. */
export async function leaveOlcrtcRoom(): Promise<void> {
  try {
    const prov = getOlcrtcProvider()
    const cfg = readOlcrtcCache(prov)
    const roomDbId = cfg?.providers?.[prov]?.room_db_id
    if (!roomDbId) {
      await sendOlcrtcHeartbeat(false)
      return
    }
    const fp = getStableDeviceFingerprint()
    const electron = (window as unknown as {
      electronAPI?: {
        tunnelApiRequest?: (p: {
          method: string
          path: string
          body?: unknown
          timeout?: number
        }) => Promise<{ status: number; data: unknown }>
      }
    }).electronAPI
    const body = {
      room_db_id: roomDbId,
      fingerprint: fp,
      provider: prov,
      device_type: 'pc',
      online: false,
    }
    try {
      if (electron?.tunnelApiRequest) {
        await electron.tunnelApiRequest({
          method: 'POST',
          path: '/api/vpn/olcrtc2-heartbeat',
          body,
          timeout: 12_000,
        })
      } else {
        const base = getPublicApiBaseUrl().replace(/\/$/, '')
        await fetch(`${base}/api/vpn/olcrtc2-heartbeat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          cache: 'no-store',
        })
      }
    } catch { /* ignore */ }
  } catch { /* ignore */ }
  // Кеш слотов не чистим — TM↔WB switch читает dual-cache.
}

function readOlcrtcCache(provider: string = getOlcrtcProvider()): OlcrtcPublicConfig | null {
  try {
    const raw = localStorage.getItem(olcrtcCacheKey(provider))
    if (!raw) {
      // миграция со старого единого ключа
      const legacy = localStorage.getItem(OLCRTC_CACHE_KEY_LEGACY)
      if (!legacy) return null
      const parsed = JSON.parse(legacy)
      const cfg = (parsed?.cfg || parsed) as OlcrtcPublicConfig | null
      if (!cfg?.providers?.[provider]?.room) return null
      saveOlcrtcCache(cfg, provider)
      return cfg
    }
    const parsed = JSON.parse(raw)
    const cfg = (parsed?.cfg || parsed) as OlcrtcPublicConfig | null
    if (!cfg?.enabled || (cfg.crypto_key?.length ?? 0) !== 64) return null
    const room = (cfg.providers?.[provider]?.room || '').trim()
    if (!room || cfg.providers?.[provider]?.enabled === false) return null
    return cfg
  } catch {
    return null
  }
}

function olcrtcConfigPath(provider: string = getOlcrtcProvider()): string {
  let fp = ''
  try {
    fp = getStableDeviceFingerprint()
  } catch {
    /* до логина */
  }
  const q = new URLSearchParams({
    device_type: 'pc',
    fingerprint: fp,
    provider,
  })
  return `/api/vpn/olcrtc2-config?${q.toString()}`
}

function saveOlcrtcCache(cfg: OlcrtcPublicConfig, forProvider?: string) {
  try {
    const slots = Object.entries(cfg.providers || {})
    let wrote = false
    for (const [rawKey, slot] of slots) {
      const k = String(rawKey || '').trim().toLowerCase()
      if (k !== OLCRTC_TELEMOST && k !== OLCRTC_WBSTREAM) continue
      if (slot?.denied || !slot?.enabled || !String(slot.room || '').trim()) continue
      localStorage.setItem(olcrtcCacheKey(k), JSON.stringify({ at: Date.now(), cfg }))
      wrote = true
    }
    // Ответ с одним слотом — сохранить явно под запрошенный provider.
    if (!wrote && forProvider) {
      const p = cfg.providers?.[forProvider]
      if (p?.enabled && String(p.room || '').trim() && !p.denied) {
        localStorage.setItem(olcrtcCacheKey(forProvider), JSON.stringify({ at: Date.now(), cfg }))
        wrote = true
      }
    }
    if (!wrote) return
    try {
      localStorage.removeItem(OLCRTC_CACHE_KEY_LEGACY)
    } catch { /* ignore */ }
    try {
      window.dispatchEvent(new CustomEvent('silent-olcrtc-config', { detail: cfg }))
    } catch { /* ignore */ }
  } catch { /* ignore */ }
}

export function clearOlcrtcCache(): void {
  try {
    localStorage.removeItem(olcrtcCacheKey(OLCRTC_TELEMOST))
    localStorage.removeItem(olcrtcCacheKey(OLCRTC_WBSTREAM))
    localStorage.removeItem(OLCRTC_CACHE_KEY_LEGACY)
  } catch { /* ignore */ }
}

export function getCachedOlcrtcConfigForProvider(
  provider: string = getOlcrtcProvider(),
): OlcrtcPublicConfig | null {
  return readOlcrtcCache(provider)
}

/** Текущий room id выбранного провайдера (из кеша после /olcrtc-config). */
export function getLiveOlcrtcRoom(provider: string = getOlcrtcProvider()): string {
  const cfg = getCachedOlcrtcConfigForProvider(provider)
  return (cfg?.providers?.[provider]?.room || '').trim()
}

/**
 * Подтянуть /olcrtc2-config (редко: login / VK sync / peer-dead).
 * Не вызывать при TM↔WB switch.
 */
export async function syncOlcrtcLiveChannel(opts?: {
  log?: (msg: string) => void
}): Promise<OlcrtcPublicConfig | null> {
  const prov = getOlcrtcProvider()
  const prevRoom = getLiveOlcrtcRoom(prov)
  const cfg = await fetchOlcrtcConfig(undefined, prov)
  if (!cfg) return getCachedOlcrtcConfigForProvider(prov)
  const nextRoom = (cfg.providers?.[prov]?.room || '').trim()
  if (nextRoom && nextRoom !== prevRoom) {
    const msg = prevRoom
      ? `канал сменился: ${olcrtcProviderLabel(prov)} ${prevRoom.slice(0, 28)} → ${nextRoom.slice(0, 28)}`
      : `канал: ${olcrtcProviderLabel(prov)} room=${nextRoom.slice(0, 48)}`
    opts?.log?.(msg)
    try {
      const { pushLog } = await import('./debugLog')
      pushLog('olcrtc', msg)
    } catch { /* ignore */ }
    if (prevRoom) {
      try {
        window.dispatchEvent(
          new CustomEvent('silent-olcrtc-room-changed', {
            detail: { provider: prov, prevRoom, nextRoom },
          }),
        )
      } catch { /* ignore */ }
    }
  }
  return cfg
}

/** Peer dead → сброс только слота текущего провайдера + новый assign. */
export async function reportOlcrtcRoomFailure(detail: string = ''): Promise<OlcrtcPublicConfig | null> {
  const prov = getOlcrtcProvider()
  const cfg = getCachedOlcrtcConfigForProvider(prov)
  const roomDbId = cfg?.providers?.[prov]?.room_db_id || ''
  const oldRoom = cfg?.providers?.[prov]?.room || ''
  try {
    const fp = getStableDeviceFingerprint()
    const base = getPublicApiBaseUrl().replace(/\/$/, '')
    const electron = (window as unknown as {
      electronAPI?: {
        tunnelApiRequest?: (p: {
          method: string
          path: string
          body?: unknown
          timeout?: number
        }) => Promise<{ status: number; data: unknown }>
      }
    }).electronAPI
    const body = {
      room_db_id: roomDbId,
      fingerprint: fp,
      provider: prov,
      device_type: 'pc',
      detail: detail || `peer dead room=${oldRoom}`,
    }
    if (electron?.tunnelApiRequest) {
      await electron.tunnelApiRequest({
        method: 'POST',
        path: '/api/vpn/olcrtc2-room-failure',
        body,
        timeout: 15_000,
      })
    } else {
      await fetch(`${base}/api/vpn/olcrtc2-room-failure`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      })
    }
  } catch { /* ignore */ }
  try {
    localStorage.removeItem(olcrtcCacheKey(prov))
  } catch { /* ignore */ }
  try {
    const { pushLog } = await import('./debugLog')
    pushLog('olcrtc', `room failure → сброс sticky, ищем новый канал (${detail || oldRoom})`)
  } catch { /* ignore */ }
  return syncOlcrtcLiveChannel()
}

let liveSyncTimer: ReturnType<typeof setInterval> | null = null

/** Live-sync по таймеру отключён (лишние /olcrtc2-config). Оставлено API для совместимости. */
export function startOlcrtcLiveSyncLoop(): void {
  stopOlcrtcLiveSyncLoop()
}

export function stopOlcrtcLiveSyncLoop(): void {
  if (liveSyncTimer) {
    clearInterval(liveSyncTimer)
    liveSyncTimer = null
  }
}

export function getCachedOlcrtcConfig(): OlcrtcPublicConfig | null {
  return getCachedOlcrtcConfigForProvider(getOlcrtcProvider())
}

/** Всегда через main IPC (bypass при VPN) → публичный API. */
export async function fetchOlcrtcConfig(
  _baseUrl?: string,
  forProvider?: string,
): Promise<OlcrtcPublicConfig | null> {
  const prov =
    forProvider === OLCRTC_WBSTREAM || forProvider === OLCRTC_TELEMOST
      ? forProvider
      : getOlcrtcProvider()
  const parseAndCache = (raw: unknown): OlcrtcPublicConfig | null => {
    const cfg = raw as OlcrtcPublicConfig
    if (!cfg || typeof cfg !== 'object') return null
    if (cfg.enabled && cfg.crypto_key?.length === 64) {
      saveOlcrtcCache(cfg, prov)
    }
    return cfg
  }

  try {
    const electron = (window as unknown as {
      electronAPI?: {
        tunnelApiRequest?: (p: {
          method: string
          path: string
          timeout?: number
        }) => Promise<{ status: number; data: unknown }>
      }
    }).electronAPI

    if (electron?.tunnelApiRequest) {
      const res = await electron.tunnelApiRequest({
        method: 'GET',
        path: olcrtcConfigPath(prov),
        timeout: 90_000,
      })
      if (res?.status >= 200 && res.status < 300) {
        const parsed = parseAndCache(res.data)
        if (parsed) return parsed
      }
    }
  } catch {
    /* fall through */
  }

  try {
    const base = (_baseUrl || getPublicApiBaseUrl()).replace(/\/$/, '')
    const res = await fetch(`${base}${olcrtcConfigPath(prov)}`, { cache: 'no-store' })
    if (!res.ok) return getCachedOlcrtcConfigForProvider(prov)
    const cfg = parseAndCache(await res.json())
    if (cfg) return cfg
    return getCachedOlcrtcConfigForProvider(prov)
  } catch {
    return getCachedOlcrtcConfigForProvider(prov)
  }
}

/** Прогрев обоих слотов — login / sync при VK. */
export async function prefetchOlcrtcBothProviders(): Promise<{ tm: boolean; wb: boolean }> {
  const tmCfg = await fetchOlcrtcConfig(undefined, OLCRTC_TELEMOST)
  const wbCfg = await fetchOlcrtcConfig(undefined, OLCRTC_WBSTREAM)
  const tm = !!(tmCfg?.providers?.[OLCRTC_TELEMOST]?.room || getCachedOlcrtcConfigForProvider(OLCRTC_TELEMOST))
  const wb = !!(wbCfg?.providers?.[OLCRTC_WBSTREAM]?.room || getCachedOlcrtcConfigForProvider(OLCRTC_WBSTREAM))
  return { tm, wb }
}

/** Один слот (текущий) — совместимость. Для login лучше prefetchOlcrtcBothProviders. */
export async function prefetchOlcrtcConfig(): Promise<OlcrtcPublicConfig | null> {
  return fetchOlcrtcConfig()
}

/** Кеш first. Сеть только если слота нет. */
export async function resolveOlcrtcConfig(opts?: {
  preferCache?: boolean
}): Promise<OlcrtcPublicConfig | null> {
  const cached = getCachedOlcrtcConfig()
  if (opts?.preferCache !== false && cached) {
    return cached
  }
  if (cached) return cached
  return (await fetchOlcrtcConfig()) || cached
}

/** Параметры для vpnConnect при family=olcrtc. */
export function buildOlcrtcConnectPayload(
  cfg: OlcrtcPublicConfig,
  provider: string = getOlcrtcProvider(),
  extra: Record<string, unknown> = {},
): Record<string, unknown> | { error: string } {
  const p = cfg.providers?.[provider]
  if (p?.denied || (cfg.pool_denied && !p?.room)) {
    return {
      error:
        cfg.pool_denied_detail ||
        'Нет свободных комнат обхода. Попробуйте позже или другой провайдер.',
    }
  }
  if (!cfg.enabled || !cfg.crypto_key || !p?.enabled || !p.room) {
    return {
      error: `olcrtc: провайдер «${olcrtcProviderLabel(provider)}» не настроен в админке (Варианты обхода → 2)`,
    }
  }
  // DNS пресет (меню DNS) — Яндекс по умолчанию; без fake-ip в sing-box.
  const dnsServers = getDnsOverrideServers() || '77.88.8.8, 77.88.8.1'
  return {
    bypassFamily: BYPASS_FAMILY_OLCRTC2,
    olcrtc_provider: provider,
    olcrtc_room: p.room,
    olcrtc_crypto_key: cfg.crypto_key,
    olcrtc_transport:
      p.transport ||
      (provider === OLCRTC_TELEMOST || provider === OLCRTC_WBSTREAM ? 'vp8channel' : 'datachannel'),
    olcrtc_socks_host: cfg.socks_host || '127.0.0.1',
    olcrtc_socks_port: cfg.socks_port || 8808,
    dns_override: dnsServers,
    wg_dns: dnsServers,
    // auth_token WB — только на srv; клиент guest (иначе carrier reconnect).
    ...extra,
  }
}
