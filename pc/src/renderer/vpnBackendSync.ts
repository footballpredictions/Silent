import axios from 'axios'

import api, { getPublicApiBaseUrl, getDeviceFingerprint } from './api'

import { pushLog } from './debugLog'

import { getCachedVpnConfig } from './vkConfig'

import { clearTunnelApiBase, setTunnelApiBase } from './tunnelApi'

const CONNECT_BODY = (fp: string) => ({
  device_fingerprint: fp,
  device_type: 'pc' as const,
})

function authHeaders() {
  const token = localStorage.getItem('silent_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Поставить «онлайн» на backend — сначала public API, затем tunnel (10.66.66.1). */
export async function notifyConnect(): Promise<boolean> {
  const fp = getDeviceFingerprint()
  const body = CONNECT_BODY(fp)
  const publicUrl = getPublicApiBaseUrl()

  try {
    const res = await axios.post(`${publicUrl}/api/vpn/connect`, body, {
      headers: authHeaders(),
      timeout: 15_000,
    })
    if (res.status >= 200 && res.status < 300) {
      pushLog('Main', 'connect API OK (public)')
      return true
    }
    pushLog('Main', `connect API public HTTP ${res.status}`, 'W')
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Main', `connect API public: ${msg}`, 'W')
  }

  const cfg = getCachedVpnConfig()
  const addr = cfg?.wg_address ?? cfg?.assigned_ip
  if (!addr?.trim()) return false

  setTunnelApiBase(addr)
  try {
    const res = await api.post('/api/vpn/connect', body)
    if (res.status >= 200 && res.status < 300) {
      pushLog('Main', 'connect API OK (tunnel)')
      return true
    }
    pushLog('Main', `connect API tunnel HTTP ${res.status}`, 'W')
    return false
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Main', `connect API tunnel: ${msg}`, 'W')
    return false
  } finally {
    clearTunnelApiBase()
  }
}

/** Снять «онлайн» на backend до остановки VPN (пока tunnel API доступен). */
export async function notifyDisconnect(): Promise<boolean> {
  try {
    const fp = getDeviceFingerprint()
    const cfg = getCachedVpnConfig()
    const addr = cfg?.wg_address ?? cfg?.assigned_ip
    if (!addr?.trim()) return false
    setTunnelApiBase(addr)
    const res = await api.post('/api/vpn/disconnect', { device_fingerprint: fp })
    if (res.status >= 200 && res.status < 300) {
      pushLog('Main', 'disconnect API OK — online cleared before tunnel stop')
      return true
    }
    pushLog('Main', `disconnect API HTTP ${res.status}`, 'W')
    return false
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Main', `disconnect API failed: ${msg}`, 'W')
    return false
  }
}
