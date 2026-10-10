import api, { formatApiError } from './api'
import { pushLog } from './debugLog'
import type { VpnConfigPayload } from './vkConfig'
import { getPreferredServer } from './bypassStore'

function hasWgKeys(config: VpnConfigPayload | null | undefined): boolean {
  return !!config?.wg_private_key?.trim() && !!config?.server_public_key?.trim()
}

function isAccessError(err: unknown): boolean {
  const status = (err as { response?: { status?: number } })?.response?.status
  return status === 402 || status === 403
}

/** Получить VPN-конфиг (register → /config) через текущий API-маршрут. */
export async function fetchVpnConfigWithKeys(fingerprint: string): Promise<VpnConfigPayload | null> {
  try {
    const preferred = getPreferredServer()
    const reg = await api.post('/api/vpn/device/register', {
      device_name: 'PC',
      device_type: 'pc',
      device_fingerprint: fingerprint,
      preferred_server: preferred,
    })
    const config = reg.data as VpnConfigPayload
    if (hasWgKeys(config)) {
      pushLog('Main', `device/register OK device=${String(config.device_id || '').slice(0, 8)} slot=${config.selected_server || ''} ip=${config.server_ip || ''} want=${preferred}`)
      return config
    }
  } catch (e) {
    if (isAccessError(e)) throw e
    pushLog('Main', `device/register fail: ${formatApiError(e, 'Network Error')}`, 'W')
  }

  try {
    const preferred = getPreferredServer()
    const cfg = await api.get(`/api/vpn/config?fingerprint=${encodeURIComponent(fingerprint)}&preferred_server=${encodeURIComponent(preferred)}`)
    const config = cfg.data as VpnConfigPayload
    if (hasWgKeys(config)) {
      pushLog('Main', `vpn/config OK device=${String(config.device_id || '').slice(0, 8)}`)
      return config
    }
  } catch (e) {
    if (isAccessError(e)) throw e
    pushLog('Main', `vpn/config fail: ${formatApiError(e, 'Network Error')}`, 'W')
  }

  return null
}
