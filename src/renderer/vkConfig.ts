import { extractCallHash } from './hashConfig'
import { getEmbeddedBootstrapHash } from './embeddedBootstrapHash'
import { getPreferredServer, slotFromSelectedServer } from './bypassStore'

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
  /** Принудительный DNS для WG (меню DNS: пресет или свой ввод). */
  dns_override?: string
  mtu?: number
  keepalive?: number
  endpoint?: string
  wdtt_password?: string
  device_id?: string
  selected_server?: string
  stream_count?: number
  vk_hashes: string[]
  client_sync?: ClientSyncBundle
}

export interface ClientSyncBundle {
  profile?: unknown
  theme?: unknown
  referral?: {
    referral_code?: string
    referral_link?: string
    invited_count?: number
    rewarded_count?: number
    pending_count?: number
    bonus_days?: number
  }
  hashes?: string[]
  sync?: { hashes?: number; theme?: number; profile?: number }
}

const REFERRAL_CACHE_KEY = 'silent_referral_cache'

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
  const preferred = getPreferredServer()
  const slot = slotFromSelectedServer(cfg.selected_server)
  // Не переклеивать ключи другого слота на текущий preferred — иначе 3→2
  // поднимает peer соты 2 при выбранном сервере 2.
  if (slot && slot !== preferred) return
  localStorage.setItem(VPN_CACHE_KEY, JSON.stringify({
    ...cfg,
    selected_server: slot || preferred,
  }))
  applyClientSyncBundle(cfg.client_sync)
}

export function applyClientSyncBundle(bundle?: ClientSyncBundle | null): void {
  if (!bundle) return
  try {
    if (bundle.profile) localStorage.setItem('silent_cached_profile_json', JSON.stringify(bundle.profile))
    if (bundle.theme) localStorage.setItem('silent_cached_theme_json', JSON.stringify(bundle.theme))
    if (bundle.referral) localStorage.setItem(REFERRAL_CACHE_KEY, JSON.stringify(bundle.referral))
    if (bundle.hashes?.length) {
      const items = bundle.hashes.map((hash, i) => ({
        hash,
        label: `Сервер ${i + 1}`,
        source: 'server',
        slot_index: i,
        is_active: true,
        status: 'active',
      }))
      localStorage.setItem('silent_saved_hash_items', JSON.stringify(items))
      localStorage.setItem('silent_saved_hash_items_ts', String(Date.now()))
    }
    const sync = bundle.sync
    if (sync) {
      if (sync.hashes) localStorage.setItem('silent_sync_hashes_rev', String(sync.hashes))
      if (sync.theme) localStorage.setItem('silent_sync_theme_rev', String(sync.theme))
      if (sync.profile) localStorage.setItem('silent_sync_profile_rev', String(sync.profile))
    }
  } catch {
    /* quota / private mode */
  }
}

export function getCachedReferral(): ClientSyncBundle['referral'] | null {
  try {
    const raw = localStorage.getItem(REFERRAL_CACHE_KEY)
    return raw ? (JSON.parse(raw) as ClientSyncBundle['referral']) : null
  } catch {
    return null
  }
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
