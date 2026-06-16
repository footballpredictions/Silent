import axios from 'axios'

import api, { getPublicApiBaseUrl, getDeviceFingerprint } from './api'

import { pushLog } from './debugLog'

import { cacheVpnConfig, getCachedVpnConfig } from './vkConfig'

import { clearTunnelApiBase, enableTunnelApi, setMainVpnSessionActive } from './tunnelApi'

import { saveSessionDeviceId } from './api'

const CONNECT_BODY = (fp: string) => ({
  device_fingerprint: fp,
  device_type: 'pc' as const,
})

function authHeaders() {
  const token = localStorage.getItem('silent_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Регистрация устройства при 404 на /connect (кеш без актуального fingerprint). */
async function ensureDeviceRegistered(fp: string, viaTunnel: boolean): Promise<boolean> {
  try {
    if (viaTunnel) enableTunnelApi()
    const res = await api.post('/api/vpn/device/register', {
      device_name: 'PC',
      device_type: 'pc',
      device_fingerprint: fp,
    })
    const config = res.data
    if (config?.device_id) {
      cacheVpnConfig(config)
      saveSessionDeviceId(String(config.device_id))
      pushLog('Main', `device/register retry OK device=${String(config.device_id).slice(0, 8)}`)
      return true
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Main', `device/register retry: ${msg}`, 'W')
  }
  return false
}

async function postConnect(fp: string, viaTunnel: boolean): Promise<{ ok: boolean; status?: number }> {
  const body = CONNECT_BODY(fp)
  try {
    const res = viaTunnel
      ? await api.post('/api/vpn/connect', body)
      : await axios.post(`${getPublicApiBaseUrl()}/api/vpn/connect`, body, {
          headers: authHeaders(),
          timeout: 30_000,
        })
    if (res.status >= 200 && res.status < 300) {
      return { ok: true }
    }
    return { ok: false, status: res.status }
  } catch (e: unknown) {
    const ax = e as { response?: { status?: number }; message?: string }
    const status = ax.response?.status
    if (status === 404) {
      const registered = await ensureDeviceRegistered(fp, viaTunnel)
      if (registered) {
        try {
          const retry = viaTunnel
            ? await api.post('/api/vpn/connect', body)
            : await axios.post(`${getPublicApiBaseUrl()}/api/vpn/connect`, body, {
                headers: authHeaders(),
                timeout: 30_000,
              })
          if (retry.status >= 200 && retry.status < 300) return { ok: true }
          return { ok: false, status: retry.status }
        } catch (re: unknown) {
          const rs = (re as { response?: { status?: number } }).response?.status
          return { ok: false, status: rs }
        }
      }
    }
    const msg = ax.message || String(e)
    pushLog('Main', viaTunnel ? `connect API tunnel: ${msg}` : `connect API public: ${msg}`, 'W')
    return { ok: false, status }
  }
}

/**
 * Поставить «онлайн» на backend.
 * При включённом VPN — сначала tunnel (10.66.66.1), tunnel API не сбрасываем.
 */
export async function notifyConnect(vpnTunnelUp = false): Promise<boolean> {
  const fp = getDeviceFingerprint()
  if (vpnTunnelUp) {
    enableTunnelApi()
    const tunnel = await postConnect(fp, true)
    if (tunnel.ok) {
      pushLog('Main', 'connect API OK (tunnel)')
      return true
    }
    pushLog('Main', `connect API tunnel HTTP ${tunnel.status ?? '?'}`, 'W')
    return false
  }

  const pub = await postConnect(fp, false)
  if (pub.ok) {
    pushLog('Main', 'connect API OK (public)')
    return true
  }
  pushLog('Main', `connect API public HTTP ${pub.status ?? '?'}`, 'W')

  if (!vpnTunnelUp) {
    enableTunnelApi()
    const tunnel = await postConnect(fp, true)
    if (tunnel.ok) {
      pushLog('Main', 'connect API OK (tunnel fallback)')
      return true
    }
    pushLog('Main', `connect API tunnel HTTP ${tunnel.status ?? '?'}`, 'W')
  }
  return false
}

/** Снять «онлайн» на backend — public HTTPS, tunnel как fallback. */
export async function notifyDisconnect(fingerprint?: string): Promise<boolean> {
  const fp = fingerprint || getDeviceFingerprint()
  const publicUrl = getPublicApiBaseUrl()

  try {
    const res = await axios.post(
      `${publicUrl}/api/vpn/disconnect`,
      { device_fingerprint: fp },
      { headers: authHeaders(), timeout: 15_000 },
    )
    if (res.status >= 200 && res.status < 300) {
      pushLog('Main', 'disconnect API OK (public)')
      return true
    }
    pushLog('Main', `disconnect API HTTP ${res.status}`, 'W')
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Main', `disconnect API public: ${msg}`, 'W')
  }

  const cfg = getCachedVpnConfig()
  const addr = cfg?.wg_address ?? cfg?.assigned_ip
  if (!addr?.trim()) return false

  enableTunnelApi()
  try {
    const res = await api.post('/api/vpn/disconnect', { device_fingerprint: fp })
    if (res.status >= 200 && res.status < 300) {
      pushLog('Main', 'disconnect API OK (tunnel)')
      return true
    }
    pushLog('Main', `disconnect API tunnel HTTP ${res.status}`, 'W')
    return false
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Main', `disconnect API tunnel: ${msg}`, 'W')
    return false
  } finally {
    setMainVpnSessionActive(false)
  }
}
