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
import { DNS_FALLBACK_SERVERS, getDnsOverrideServers } from './dnsPreset'
import { isolateOlcrtcCachePayload } from './olcrtcCachePolicy.mjs'

const FAMILY_KEY = 'bypass_family'
const OLCRTC_PROVIDER_KEY = 'olcrtc_provider'
const PREFERRED_SERVER_KEY = 'preferred_server'
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
  const v =
    family === BYPASS_FAMILY_OLCRTC || family === BYPASS_FAMILY_OLCRTC2
      ? BYPASS_FAMILY_OLCRTC2
      : BYPASS_FAMILY_WDTT
  try {
    localStorage.setItem(FAMILY_KEY, v)
  } catch { /* ignore */ }
}

export function normalizePreferredServer(raw?: string | null): string {
  const v = String(raw || '').trim().toLowerCase()
  if (!v || v === 'queen' || v === 'main') return 'server1'
  if (/^server\d+$/.test(v)) return v
  return 'server1'
}

export function getPreferredServer(): string {
  try {
    return normalizePreferredServer(localStorage.getItem(PREFERRED_SERVER_KEY))
  } catch { /* ignore */ }
  return 'server1'
}

export function slotFromSelectedServer(selected?: string | null): string | null {
  const raw = String(selected || '').trim().toLowerCase()
  if (!raw || raw === 'queen' || raw === 'main') return 'server1'
  if (/^server\d+$/.test(raw)) return raw
  return null
}

export function cachedConfigMatchesPreferred(cfg: { selected_server?: string } | null | undefined): boolean {
  if (!cfg) return false
  const slot = slotFromSelectedServer(cfg.selected_server)
  if (!slot) return false
  return slot === getPreferredServer()
}

export function setPreferredServer(server: string) {
  const normalized = normalizePreferredServer(server)
  try {
    localStorage.setItem(PREFERRED_SERVER_KEY, normalized)
  } catch { /* ignore */ }
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
  try {
    localStorage.setItem(OLCRTC_PROVIDER_KEY, normalized)
  } catch { /* ignore */ }
}

export function isOlcrtcBypass(): boolean {
  return getBypassFamily() === BYPASS_FAMILY_OLCRTC2
}

export function olcrtcProviderLabel(provider: string = getOlcrtcProvider()): string {
  switch (provider) {
    case OLCRTC_WBSTREAM: return 'WB Stream'
    case OLCRTC_TELEMOST: return 'Яндекс Телемост'
    default: return 'Яндекс Телемост'
  }
}

export function bypassFamilyLabel(family: string = getBypassFamily()): string {
  void family
  return 'сервер'
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

type OlcrtcCacheEnvelope = {
  at?: number
  cfg?: OlcrtcPublicConfig
}

let heartbeatTimer: ReturnType<typeof setInterval> | null = null

type ElectronOlcrtcApi = {
  tunnelApiRequest?: (p: {
    method: string
    path: string
    body?: unknown
    timeout?: number
  }) => Promise<{ status: number; data: unknown }>
  olcrtc2ApiViaSocks?: (p: {
    method: string
    path: string
    body?: unknown
    timeout?: number
  }) => Promise<{ ok?: boolean; status?: number; reason?: string; data?: unknown }>
}

async function postOlcrtc2Json(
  path: string,
  body: unknown,
  timeout = 15_000,
): Promise<{ status: number; via: string }> {
  const electron = (window as unknown as { electronAPI?: ElectronOlcrtcApi }).electronAPI
  if (electron?.olcrtc2ApiViaSocks) {
    const socks = await electron.olcrtc2ApiViaSocks({ method: 'POST', path, body, timeout })
    if (socks?.ok && (socks.status ?? 0) >= 200 && (socks.status ?? 0) < 500) {
      return { status: socks.status || 200, via: 'socks' }
    }
  }
  if (electron?.tunnelApiRequest) {
    const res = await electron.tunnelApiRequest({ method: 'POST', path, body, timeout })
    return { status: res?.status || 0, via: 'tunnel' }
  }
  const base = getPublicApiBaseUrl().replace(/\/$/, '')
  const res = await fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  })
  return { status: res.status, via: 'public' }
}

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
    const res = await postOlcrtc2Json('/api/vpn/olcrtc2-heartbeat', body, 15_000)
    if (online && (res.status < 200 || res.status >= 300)) {
      try {
        const { pushLog } = await import('./debugLog')
        pushLog('olcrtc', `heartbeat HTTP ${res.status} via ${res.via}`, 'W')
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
    const body = {
      room_db_id: roomDbId,
      fingerprint: fp,
      provider: prov,
      device_type: 'pc',
      online: false,
    }
    try {
      await postOlcrtc2Json('/api/vpn/olcrtc2-heartbeat', body, 12_000)
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

function readOlcrtcCacheEnvelope(provider: string = getOlcrtcProvider()): OlcrtcCacheEnvelope | null {
  try {
    const raw = localStorage.getItem(olcrtcCacheKey(provider))
    if (!raw) return null
    const parsed = JSON.parse(raw) as OlcrtcCacheEnvelope
    if (parsed && typeof parsed === 'object' && (parsed.cfg || parsed.at)) return parsed
    return null
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
    const prov =
      forProvider === OLCRTC_WBSTREAM || forProvider === OLCRTC_TELEMOST
        ? forProvider
        : getOlcrtcProvider()
    const isolated = isolateOlcrtcCachePayload(cfg, prov) as OlcrtcPublicConfig | null
    if (!isolated) return
    localStorage.setItem(olcrtcCacheKey(prov), JSON.stringify({ at: Date.now(), cfg: isolated }))
    try {
      localStorage.removeItem(OLCRTC_CACHE_KEY_LEGACY)
    } catch { /* ignore */ }
    try {
      window.dispatchEvent(new CustomEvent('silent-olcrtc-config', { detail: isolated }))
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

export function getOlcrtcCacheAgeMs(provider: string = getOlcrtcProvider()): number | null {
  const env = readOlcrtcCacheEnvelope(provider)
  const at = Number(env?.at || 0)
  if (!Number.isFinite(at) || at <= 0) return null
  return Math.max(0, Date.now() - at)
}

export function shouldRefreshOlcrtcSlot(
  provider: string = getOlcrtcProvider(),
  opts?: { force?: boolean; maxAgeMs?: number },
): boolean {
  if (opts?.force) return true
  const cfg = getCachedOlcrtcConfigForProvider(provider)
  const room = (cfg?.providers?.[provider]?.room || '').trim()
  if (!room) return true
  const age = getOlcrtcCacheAgeMs(provider)
  if (age == null) return true
  const maxAge = opts?.maxAgeMs ?? 8 * 60 * 1000
  return age >= maxAge
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

let lastFailedOlcrtcRoom = ''
let lastFailureReportAtMs = 0
let lastFailureReportRoom = ''
const FAILURE_REPORT_DEBOUNCE_MS = 8_000

/** Peer dead → сброс только слота текущего провайдера + новый assign. */
export async function reportOlcrtcRoomFailure(detail: string = ''): Promise<OlcrtcPublicConfig | null> {
  const prov = getOlcrtcProvider()
  const cfg = getCachedOlcrtcConfigForProvider(prov)
  const roomDbId = cfg?.providers?.[prov]?.room_db_id || ''
  const oldRoom = cfg?.providers?.[prov]?.room || ''
  const now = Date.now()
  if (
    oldRoom &&
    oldRoom === lastFailureReportRoom &&
    now - lastFailureReportAtMs < FAILURE_REPORT_DEBOUNCE_MS
  ) {
    return getCachedOlcrtcConfigForProvider(prov)
  }
  if (oldRoom) lastFailedOlcrtcRoom = oldRoom
  try {
    const fp = getStableDeviceFingerprint()
    const body = {
      room_db_id: roomDbId,
      fingerprint: fp,
      provider: prov,
      device_type: 'pc',
      detail: detail || `peer dead room=${oldRoom}`,
    }
    await postOlcrtc2Json('/api/vpn/olcrtc2-room-failure', body, 15_000)
  } catch { /* ignore */ }
  lastFailureReportAtMs = now
  lastFailureReportRoom = oldRoom
  // Кеш слота не затираем: сохраняем last-known-good до подтверждения новой room.
  // Старт на старой room блокируется через lastFailedOlcrtcRoom.
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

/** Всегда через main IPC. При живом VPN main не падает в public (БС). */
export async function fetchOlcrtcConfig(
  _baseUrl?: string,
  forProvider?: string,
): Promise<OlcrtcPublicConfig | null> {
  const prov =
    forProvider === OLCRTC_WBSTREAM || forProvider === OLCRTC_TELEMOST
      ? forProvider
      : getOlcrtcProvider()
  const parseAndCache = (raw: unknown): OlcrtcPublicConfig | null => {
    const isolated = isolateOlcrtcCachePayload(raw, prov) as OlcrtcPublicConfig | null
    if (!isolated) return null
    const room = String(isolated.providers?.[prov]?.room || '').trim()
    if (lastFailedOlcrtcRoom && room && room === lastFailedOlcrtcRoom) return null
    saveOlcrtcCache(isolated, prov)
    if (room && room !== lastFailedOlcrtcRoom) lastFailedOlcrtcRoom = ''
    return isolated
  }

  try {
    const electron = (window as unknown as { electronAPI?: ElectronOlcrtcApi }).electronAPI

    if (electron?.olcrtc2ApiViaSocks) {
      try {
        const socks = await electron.olcrtc2ApiViaSocks({
          method: 'GET',
          path: olcrtcConfigPath(prov),
          timeout: 90_000,
        })
        if (socks?.ok && (socks.status ?? 0) >= 200 && (socks.status ?? 0) < 300 && socks.data) {
          const parsed = parseAndCache(socks.data)
          if (parsed) return parsed
        }
      } catch {
        /* socks down — tunnel / public */
      }
    }

    if (electron?.tunnelApiRequest) {
      try {
        const res = await electron.tunnelApiRequest({
          method: 'GET',
          path: olcrtcConfigPath(prov),
          timeout: 90_000,
        })
        if (res?.status >= 200 && res.status < 300) {
          const parsed = parseAndCache(res.data)
          if (parsed) return parsed
        }
        return getCachedOlcrtcConfigForProvider(prov)
      } catch {
        return getCachedOlcrtcConfigForProvider(prov)
      }
    }
  } catch {
    /* fall through to public only without Electron */
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

export async function refreshOlcrtcSlotFast(
  provider: string,
  timeoutMs = 15_000,
): Promise<{ ok: boolean; room: string; timedOut: boolean }> {
  const prov =
    provider === OLCRTC_WBSTREAM || provider === OLCRTC_TELEMOST
      ? provider
      : getOlcrtcProvider()
  const task = fetchOlcrtcConfig(undefined, prov)
  const timeout = new Promise<null>((resolve) => {
    setTimeout(() => resolve(null), Math.max(3_000, timeoutMs))
  })
  const cfg = (await Promise.race([task, timeout])) as OlcrtcPublicConfig | null
  const fromCache = getCachedOlcrtcConfigForProvider(prov)
  const room = (cfg?.providers?.[prov]?.room || fromCache?.providers?.[prov]?.room || '').trim()
  return {
    ok: Boolean(cfg && room),
    room,
    timedOut: cfg == null && !room,
  }
}

/** Прогрев обоих слотов — login / sync при VK. Живой слот не refresh. */
export async function prefetchOlcrtcBothProviders(): Promise<{ tm: boolean; wb: boolean }> {
  const ensure = async (p: string): Promise<boolean> => {
    if (getCachedOlcrtcConfigForProvider(p)) return true
    await fetchOlcrtcConfig(undefined, p)
    return !!getCachedOlcrtcConfigForProvider(p)
  }
  const tm = await ensure(OLCRTC_TELEMOST)
  const wb = await ensure(OLCRTC_WBSTREAM)
  return { tm, wb }
}

/** Один слот (текущий) — совместимость. Для login лучше prefetchOlcrtcBothProviders. */
export async function prefetchOlcrtcConfig(): Promise<OlcrtcPublicConfig | null> {
  return fetchOlcrtcConfig()
}

/** Кеш first. Сеть только если слота нет. Не поднимать lastFailed room. */
export async function resolveOlcrtcConfig(opts?: {
  preferCache?: boolean
}): Promise<OlcrtcPublicConfig | null> {
  const cached = getCachedOlcrtcConfig()
  const prov = getOlcrtcProvider()
  const cachedRoom = (cached?.providers?.[prov]?.room || '').trim()
  if (cachedRoom && lastFailedOlcrtcRoom && cachedRoom === lastFailedOlcrtcRoom) {
    return (await fetchOlcrtcConfig()) || null
  }
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
  // Для olcrtc всегда держим fallback DNS:
  // WB — fallback first (стабильность), TM — custom first.
  const dnsServers = buildStableOlcrtcDnsServers(provider)
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

function buildStableOlcrtcDnsServers(provider: string): string {
  const fallback = DNS_FALLBACK_SERVERS.split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const custom = String(getDnsOverrideServers() || '')
    .split(',')
    .map((s) => s.trim())
    .filter((s) => /^\d{1,3}(?:\.\d{1,3}){3}$/.test(s))
  if (!custom.length) return fallback.join(', ')
  const merged =
    provider === OLCRTC_WBSTREAM
      ? [...fallback, ...custom]
      : [...custom, ...fallback]
  return Array.from(new Set(merged)).slice(0, 4).join(', ')
}
