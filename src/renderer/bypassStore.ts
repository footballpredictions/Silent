import { isDebugBuild } from './debugBuild'
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

const FAMILY_KEY = 'bypass_family'
const OLCRTC_PROVIDER_KEY = 'olcrtc_provider'
/** v3: android room → meet.small-dm.ru (LTE DPI) */
const OLCRTC_CACHE_KEY = 'olcrtc_config_cache_v9'

export const BYPASS_FAMILY_WDTT = 'wdtt'
export const BYPASS_FAMILY_OLCRTC = 'olcrtc'

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
    if (v === BYPASS_FAMILY_OLCRTC) return BYPASS_FAMILY_OLCRTC
  } catch { /* ignore */ }
  return BYPASS_FAMILY_WDTT
}

export function setBypassFamily(family: string) {
  if (!isDebugBuild) return
  const normalized = family === BYPASS_FAMILY_OLCRTC ? BYPASS_FAMILY_OLCRTC : BYPASS_FAMILY_WDTT
  localStorage.setItem(FAMILY_KEY, normalized)
}

export function getOlcrtcProvider(): string {
  if (!isDebugBuild) return OLCRTC_TELEMOST
  try {
    const v = localStorage.getItem(OLCRTC_PROVIDER_KEY)
    if (v === OLCRTC_WBSTREAM || v === OLCRTC_TELEMOST) return v
    // старый jitsi → telemost
    if (v === OLCRTC_JITSI) return OLCRTC_TELEMOST
  } catch { /* ignore */ }
  return OLCRTC_TELEMOST
}

export function setOlcrtcProvider(provider: string) {
  if (!isDebugBuild) return
  const normalized =
    provider === OLCRTC_WBSTREAM || provider === OLCRTC_TELEMOST
      ? provider
      : OLCRTC_TELEMOST
  localStorage.setItem(OLCRTC_PROVIDER_KEY, normalized)
}

export function isOlcrtcBypass(): boolean {
  return getBypassFamily() === BYPASS_FAMILY_OLCRTC
}

export function olcrtcProviderLabel(provider: string = getOlcrtcProvider()): string {
  switch (provider) {
    case OLCRTC_WBSTREAM: return 'WB Stream'
    case OLCRTC_TELEMOST: return 'Яндекс Телемост'
    default: return 'Яндекс Телемост'
  }
}

export function bypassFamilyLabel(family: string = getBypassFamily()): string {
  return family === BYPASS_FAMILY_OLCRTC ? 'olcrtc' : 'VK'
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
    if (!roomDbId) return
    const base = getPublicApiBaseUrl().replace(/\/$/, '')
    const fp = getStableDeviceFingerprint()
    await fetch(`${base}/api/vpn/olcrtc-heartbeat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        room_db_id: roomDbId,
        fingerprint: fp,
        provider: prov,
        online,
      }),
      cache: 'no-store',
    })
  } catch { /* ignore */ }
}

export function startOlcrtcHeartbeatLoop(): void {
  stopOlcrtcHeartbeatLoop()
  void sendOlcrtcHeartbeat(true)
  heartbeatTimer = setInterval(() => {
    void sendOlcrtcHeartbeat(true)
  }, 45_000)
}

export function stopOlcrtcHeartbeatLoop(): void {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  void sendOlcrtcHeartbeat(false)
}

function readOlcrtcCache(): OlcrtcPublicConfig | null {
  try {
    const raw = localStorage.getItem(OLCRTC_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed?.cfg || null
  } catch {
    return null
  }
}

function olcrtcConfigPath(): string {
  let fp = ''
  try {
    fp = getStableDeviceFingerprint()
  } catch {
    /* до логина */
  }
  const q = new URLSearchParams({ device_type: 'pc', fingerprint: fp })
  return `/api/vpn/olcrtc-config?${q.toString()}`
}

function saveOlcrtcCache(cfg: OlcrtcPublicConfig) {
  try {
    localStorage.setItem(OLCRTC_CACHE_KEY, JSON.stringify({ at: Date.now(), cfg }))
    try {
      window.dispatchEvent(new CustomEvent('silent-olcrtc-config', { detail: cfg }))
    } catch { /* ignore */ }
  } catch { /* ignore */ }
}

export function clearOlcrtcCache(): void {
  try {
    localStorage.removeItem(OLCRTC_CACHE_KEY)
  } catch { /* ignore */ }
}

/** Текущий room id выбранного провайдера (из кеша после /olcrtc-config). */
export function getLiveOlcrtcRoom(provider: string = getOlcrtcProvider()): string {
  const cfg = getCachedOlcrtcConfig()
  return (cfg?.providers?.[provider]?.room || '').trim()
}

/**
 * Подтянуть /olcrtc-config; если room сменился — лог + событие для UI настроек.
 * Вызывать при connect, ConfigSync и после peer-dead.
 */
export async function syncOlcrtcLiveChannel(opts?: {
  log?: (msg: string) => void
}): Promise<OlcrtcPublicConfig | null> {
  const prov = getOlcrtcProvider()
  const prevRoom = getLiveOlcrtcRoom(prov)
  const cfg = await fetchOlcrtcConfig()
  if (!cfg) return null
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

/** Peer dead / SOCKS timeout → сервер снимет sticky; клиент сбросит кеш и возьмёт новый room. */
export async function reportOlcrtcRoomFailure(detail: string = ''): Promise<OlcrtcPublicConfig | null> {
  const cfg = getCachedOlcrtcConfig()
  const prov = getOlcrtcProvider()
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
        path: '/api/vpn/olcrtc-room-failure',
        body,
        timeout: 15_000,
      })
    } else {
      await fetch(`${base}/api/vpn/olcrtc-room-failure`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        cache: 'no-store',
      })
    }
  } catch { /* ignore */ }
  clearOlcrtcCache()
  try {
    const { pushLog } = await import('./debugLog')
    pushLog('olcrtc', `room failure → сброс sticky, ищем новый канал (${detail || oldRoom})`)
  } catch { /* ignore */ }
  return syncOlcrtcLiveChannel()
}

let liveSyncTimer: ReturnType<typeof setInterval> | null = null

/** Пока VPN/сессия olcrtc — раз в минуту сверять room с сервером (админ сменил канал). */
export function startOlcrtcLiveSyncLoop(): void {
  if (!isDebugBuild) return
  stopOlcrtcLiveSyncLoop()
  void syncOlcrtcLiveChannel()
  liveSyncTimer = setInterval(() => {
    void syncOlcrtcLiveChannel()
  }, 60_000)
}

export function stopOlcrtcLiveSyncLoop(): void {
  if (liveSyncTimer) {
    clearInterval(liveSyncTimer)
    liveSyncTimer = null
  }
}

export function getCachedOlcrtcConfig(): OlcrtcPublicConfig | null {
  try {
    const raw = localStorage.getItem(OLCRTC_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { cfg?: OlcrtcPublicConfig }
    const cfg = parsed?.cfg
    if (!cfg?.enabled || !cfg.crypto_key || cfg.crypto_key.length !== 64) return null
    return cfg
  } catch {
    return null
  }
}

/** Всегда через main IPC (bypass при VPN) → публичный API. Renderer fetch на nip.io часто таймаутит. */
export async function fetchOlcrtcConfig(
  _baseUrl?: string,
): Promise<OlcrtcPublicConfig | null> {
  const parseAndCache = (raw: unknown): OlcrtcPublicConfig | null => {
    const cfg = raw as OlcrtcPublicConfig
    if (cfg?.enabled && cfg.crypto_key?.length === 64) {
      saveOlcrtcCache(cfg)
      return cfg
    }
    return null
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
        path: olcrtcConfigPath(),
        timeout: 20_000,
      })
      if (res?.status >= 200 && res.status < 300) {
        const cached = parseAndCache(res.data)
        if (cached) return cached
      }
    }
  } catch {
    /* fall through */
  }

  try {
    const base = (_baseUrl || getPublicApiBaseUrl()).replace(/\/$/, '')
    const res = await fetch(`${base}${olcrtcConfigPath()}`, { cache: 'no-store' })
    if (!res.ok) return getCachedOlcrtcConfig()
    const cfg = parseAndCache(await res.json())
    return cfg || getCachedOlcrtcConfig()
  } catch {
    return getCachedOlcrtcConfig()
  }
}

/** Подтянуть конфиг заранее (после логина / вместе с ConfigSync). */
export async function prefetchOlcrtcConfig(): Promise<OlcrtcPublicConfig | null> {
  if (!isDebugBuild) return null
  return fetchOlcrtcConfig()
}

/** Кеш → сеть. Для connect: не ждать сеть, если кеш уже есть. */
export async function resolveOlcrtcConfig(opts?: {
  preferCache?: boolean
}): Promise<OlcrtcPublicConfig | null> {
  const cached = getCachedOlcrtcConfig()
  if (opts?.preferCache && cached) {
    void fetchOlcrtcConfig() // обновить в фоне
    return cached
  }
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
  return {
    bypassFamily: BYPASS_FAMILY_OLCRTC,
    olcrtc_provider: provider,
    olcrtc_room: p.room,
    olcrtc_crypto_key: cfg.crypto_key,
    olcrtc_transport: p.transport || 'datachannel',
    olcrtc_socks_host: cfg.socks_host || '127.0.0.1',
    olcrtc_socks_port: cfg.socks_port || 8808,
    ...(p.auth_token ? { olcrtc_auth_token: p.auth_token } : {}),
    ...extra,
  }
}
