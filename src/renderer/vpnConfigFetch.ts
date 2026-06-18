import api, { formatApiError } from './api'
import { clearTunnelApiBase, isMainVpnSessionActive } from './tunnelApi'
import { pushLog } from './debugLog'
import type { VpnConfigPayload } from './vkConfig'

function hasWgKeys(config: VpnConfigPayload | null | undefined): boolean {
  return !!config?.wg_private_key?.trim() && !!config?.server_public_key?.trim()
}

function isSubscriptionError(err: unknown): boolean {
  return (err as { response?: { status?: number } })?.response?.status === 402
}

/** Получить VPN-конфиг (register → /config). При активном VPN — только через tunnel API. */
export async function fetchVpnConfigWithKeys(fingerprint: string): Promise<VpnConfigPayload | null> {
  if (isMainVpnSessionActive()) {
    // Полный туннель — public nip.io недоступен, не сбрасываем tunnel base.
  } else {
    clearTunnelApiBase()
  }

  try {
    const reg = await api.post('/api/vpn/device/register', {
      device_name: 'PC',
      device_type: 'pc',
      device_fingerprint: fingerprint,
    })
    const config = reg.data as VpnConfigPayload
    if (hasWgKeys(config)) {
      pushLog('Main', `device/register OK device=${String(config.device_id || '').slice(0, 8)}`)
      return config
    }
  } catch (e) {
    if (isSubscriptionError(e)) throw e
    pushLog('Main', `device/register fail: ${formatApiError(e, 'Network Error')}`, 'W')
  }

  try {
    const cfg = await api.get(`/api/vpn/config?fingerprint=${encodeURIComponent(fingerprint)}`)
    const config = cfg.data as VpnConfigPayload
    if (hasWgKeys(config)) {
      pushLog('Main', `vpn/config OK device=${String(config.device_id || '').slice(0, 8)}`)
      return config
    }
  } catch (e) {
    pushLog('Main', `vpn/config fail: ${formatApiError(e, 'Network Error')}`, 'W')
  }

  return null
}
