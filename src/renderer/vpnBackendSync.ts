import axios from 'axios'

import api, { getDeviceFingerprint } from './api'

import { pushLog } from './debugLog'

import { cacheVpnConfig, getCachedVpnConfig } from './vkConfig'

import { saveSessionDeviceId } from './api'

const CONNECT_BODY = (fp: string) => ({
  device_fingerprint: fp,
  device_type: 'pc' as const,
})

function authHeaders() {
  const token = localStorage.getItem('silent_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function sleep(ms: number) {
  return new Promise(r => setTimeout(r, ms))
}

async function ensureDeviceRegistered(fp: string): Promise<boolean> {
  try {
    const res = await api.post('/api/vpn/device/register', {
      device_name: 'PC',
      device_type: 'pc',
      device_fingerprint: fp,
    })
    const config = res.data
    if (config?.device_id) {
      cacheVpnConfig(config)
      saveSessionDeviceId(String(config.device_id))
      return true
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    pushLog('Main', `device/register: ${msg}`, 'W')
  }
  return false
}

/** PC: connect/disconnect — tunnel API (10.66.66.1), fallback public direct IP. */
export async function notifyConnect(vpnTunnelUp = false): Promise<boolean> {
  const fp = getDeviceFingerprint()
  let lastMsg = ''

  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const res = await api.post('/api/vpn/connect', CONNECT_BODY(fp), {
        headers: authHeaders(),
        timeout: 45_000,
      })
      if (res.status >= 200 && res.status < 300) {
        pushLog('Main', 'connect API OK')
        return true
      }
    } catch (e: unknown) {
      const ax = e as { response?: { status?: number }; message?: string }
      lastMsg = ax.message || String(e)
      if (ax.response?.status === 404 && (await ensureDeviceRegistered(fp))) {
        continue
      }
      if (attempt < 3) {
        await sleep(2000)
        continue
      }
      try {
        const retry = await api.post('/api/vpn/connect', CONNECT_BODY(fp), {
          headers: authHeaders(),
          timeout: 45_000,
        })
        if (retry.status >= 200 && retry.status < 300) {
          pushLog('Main', 'connect API OK')
          return true
        }
      } catch { /* fall through */ }
    }
  }

  if (lastMsg) {
    pushLog('Main', `connect API: ${lastMsg}`, 'W')
  }
  return false
}

export async function notifyDisconnect(fingerprint?: string): Promise<boolean> {
  const fp = fingerprint || getDeviceFingerprint()
  try {
    const res = await api.post(
      '/api/vpn/disconnect',
      { device_fingerprint: fp },
      { headers: authHeaders(), timeout: 15_000 },
    )
    return res.status >= 200 && res.status < 300
  } catch {
    return false
  }
}
