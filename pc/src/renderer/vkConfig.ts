const PREFIX = 'SILENT:v1:'
const PEPPER = 'silent_vpn_config_v1'
const APP_ID = 54610377
const GROUP_ID = 239092728

export interface VpnConfigPayload {
  device_id: string
  wg_private_key: string
  wg_address: string
  wg_dns: string
  server_ip: string
  server_port: number
  server_public_key: string
  wdtt_password: string
  vk_hashes: string[]
  stream_count: number
}

export async function decryptVkMessageAsync(vkUserId: number, message: string): Promise<VpnConfigPayload | null> {
  if (!message.startsWith(PREFIX)) return null
  try {
    const blob = message.slice(PREFIX.length)
    const padded = blob + '='.repeat((4 - (blob.length % 4)) % 4)
    const binary = atob(padded.replace(/-/g, '+').replace(/_/g, '/'))
    const raw = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) raw[i] = binary.charCodeAt(i)
    const nonce = raw.slice(0, 12)
    const ciphertext = raw.slice(12)
    const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${vkUserId}:${APP_ID}:${PEPPER}`))
    const cryptoKey = await crypto.subtle.importKey('raw', hash, { name: 'AES-GCM' }, false, ['decrypt'])
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce }, cryptoKey, ciphertext)
    return JSON.parse(new TextDecoder().decode(plain)) as VpnConfigPayload
  } catch {
    return null
  }
}

export async function fetchConfigFromVk(vkUserId: number, accessToken: string | null): Promise<VpnConfigPayload | null> {
  if (!accessToken) return null
  const peerId = -GROUP_ID
  const url = `https://api.vk.com/method/messages.getHistory?peer_id=${peerId}&count=20&rev=0&access_token=${accessToken}&v=5.199`
  try {
    const res = await fetch(url)
    const data = await res.json()
    if (data.error) return null
    const items = data.response?.items || []
    let best: VpnConfigPayload | null = null
    let bestTs = 0
    for (const item of items) {
      if ((item.from_id || 0) > 0) continue
      const text = item.text || ''
      if (!text.startsWith(PREFIX)) continue
      const ts = item.date || 0
      if (Date.now() / 1000 - ts > 3600) continue
      const cfg = await decryptVkMessageAsync(vkUserId, text)
      if (!cfg?.vk_hashes?.length) continue
      if (ts >= bestTs) { bestTs = ts; best = cfg }
    }
    return best
  } catch {
    return null
  }
}

export function cacheVpnConfig(config: VpnConfigPayload) {
  localStorage.setItem('silent_vpn_config_cache', JSON.stringify(config))
  localStorage.setItem('silent_vpn_config_cache_ts', String(Date.now()))
}

export function clearCachedVpnConfig() {
  localStorage.removeItem('silent_vpn_config_cache')
  localStorage.removeItem('silent_vpn_config_cache_ts')
}

export function getCachedVpnConfig(): VpnConfigPayload | null {
  const ts = Number(localStorage.getItem('silent_vpn_config_cache_ts') || '0')
  if (Date.now() - ts > 30 * 60 * 1000) return null
  const raw = localStorage.getItem('silent_vpn_config_cache')
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
}

export function getVkUserId(): number {
  return Number(localStorage.getItem('silent_vk_user_id') || '0')
}

export function saveVkUserId(id: number) {
  localStorage.setItem('silent_vk_user_id', String(id))
}

export function getVkAccessToken(): string | null {
  return localStorage.getItem('silent_vk_access_token')
}

export function saveVkAccessToken(token: string) {
  localStorage.setItem('silent_vk_access_token', token)
}

export function openVkMessagesAuth() {
  const url = `https://oauth.vk.com/authorize?client_id=${APP_ID}&display=page&redirect_uri=https://oauth.vk.com/blank.html&scope=messages,offline&response_type=token&v=5.199`
  ;(window as any).electronAPI?.openExternal(url)
}
