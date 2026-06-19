import { extractCallHash } from './hashConfig'
import { getEmbeddedBootstrapHash } from './embeddedBootstrapHash'

const BOOT_HASH_KEY = 'silent_vk_bootstrap_hash'
const VK_ACCESS_KEY = 'silent_vk_access_token'
const VK_USER_ID_KEY = 'silent_vk_user_id'
const VPN_CACHE_KEY = 'silent_vpn_config_cache'

export interface VpnConfigPayload {
  wg_private_key?: string
  wg_address?: string
  server_public_key?: string
  server_ip: string
  server_port: number
  assigned_ip?: string
  wg_dns?: string
  dns?: string
  mtu?: number
  keepalive?: number
  endpoint?: string
  wdtt_password?: string
  device_id?: string
  stream_count?: number
  vk_hashes: string[]
}

export function saveBootstrapHash(_hash: string) {
  // Хеш задаётся при сборке (debug — фиксированный, release — BOOTSTRAP_VK_HASH).
}

export function getBootstrapHash(): string | null {
  const raw = getEmbeddedBootstrapHash()
  return extractCallHash(raw) || raw.trim() || null
}

export function clearBootstrapHash() {
  localStorage.removeItem(BOOT_HASH_KEY)
}

export function getVkAccessToken(): string | null {
  return localStorage.getItem(VK_ACCESS_KEY)
}

export function saveVkAccessToken(token: string) {
  localStorage.setItem(VK_ACCESS_KEY, token)
}

export function getVkUserId(): number | null {
  const raw = localStorage.getItem(VK_USER_ID_KEY)
  if (!raw) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

export function saveVkUserId(id: number) {
  localStorage.setItem(VK_USER_ID_KEY, String(id))
}

export function cacheVpnConfig(cfg: VpnConfigPayload) {
  if (!cfg.wg_private_key?.trim() || !cfg.server_public_key?.trim()) return
  localStorage.setItem(VPN_CACHE_KEY, JSON.stringify(cfg))
}

export function getCachedVpnConfig(): VpnConfigPayload | null {
  try {
    const raw = localStorage.getItem(VPN_CACHE_KEY)
    return raw ? (JSON.parse(raw) as VpnConfigPayload) : null
  } catch {
    return null
  }
}

export function clearCachedVpnConfig() {
  localStorage.removeItem(VPN_CACHE_KEY)
}

export async function fetchConfigFromVk(_vkUserId: number, _vkToken: string | null): Promise<VpnConfigPayload | null> {
  // Fallback disabled in this build: config is obtained from backend APIs.
  return null
}
