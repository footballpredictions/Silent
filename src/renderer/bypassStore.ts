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
const OLCRTC_CACHE_KEY = 'olcrtc_config_cache_v3'

export const BYPASS_FAMILY_WDTT = 'wdtt'
export const BYPASS_FAMILY_OLCRTC = 'olcrtc'

export const OLCRTC_JITSI = 'jitsi'
export const OLCRTC_WBSTREAM = 'wbstream'
export const OLCRTC_TELEMOST = 'telemost'

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
  if (!isDebugBuild) return OLCRTC_JITSI
  try {
    const v = localStorage.getItem(OLCRTC_PROVIDER_KEY)
    if (v === OLCRTC_WBSTREAM || v === OLCRTC_TELEMOST || v === OLCRTC_JITSI) return v
  } catch { /* ignore */ }
  return OLCRTC_JITSI
}

export function setOlcrtcProvider(provider: string) {
  if (!isDebugBuild) return
  const normalized =
    provider === OLCRTC_WBSTREAM || provider === OLCRTC_TELEMOST ? provider : OLCRTC_JITSI
  localStorage.setItem(OLCRTC_PROVIDER_KEY, normalized)
}

export function isOlcrtcBypass(): boolean {
  return getBypassFamily() === BYPASS_FAMILY_OLCRTC
}

export function olcrtcProviderLabel(provider: string = getOlcrtcProvider()): string {
  switch (provider) {
    case OLCRTC_WBSTREAM: return 'WB Stream'
    case OLCRTC_TELEMOST: return 'Яндекс Телемост'
    default: return 'Jitsi Meet'
  }
}

export function bypassFamilyLabel(family: string = getBypassFamily()): string {
  return family === BYPASS_FAMILY_OLCRTC ? 'olcrtc' : 'VK / WDTT'
}

export type OlcrtcPublicConfig = {
  enabled: boolean
  crypto_key: string
  socks_host?: string
  socks_port?: number
  assigned_slot?: string
  device_type?: string
  providers: Record<
    string,
    {
      enabled: boolean
      room: string
      transport: string
      room_slot_id?: string
      rooms_count?: number
    }
  >
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
  } catch { /* ignore */ }
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
    ...extra,
  }
}
