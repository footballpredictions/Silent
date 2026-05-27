import api from './api'
import { getBootstrapHash, type VpnConfigPayload } from './vkConfig'
import { pushLog } from './debugLog'

const PRE_LOGIN_FP_KEY = 'silent_pre_login_fp'

export function getPreLoginFingerprint(): string {
  let fp = localStorage.getItem(PRE_LOGIN_FP_KEY)
  if (!fp) {
    fp = crypto.randomUUID()
    localStorage.setItem(PRE_LOGIN_FP_KEY, fp)
  }
  return fp
}

export async function fetchBootstrapConfig(): Promise<VpnConfigPayload | null> {
  const boot = getBootstrapHash()
  if (!boot) return null
  pushLog('Bootstrap', `fetch config hash=${boot.slice(0, 12)}…`)
  try {
    const res = await api.post('/api/vpn/bootstrap-config', {
      bootstrap_hash: boot,
      device_type: 'pc',
      device_fingerprint: getPreLoginFingerprint(),
    })
    pushLog('Bootstrap', `config OK device=${String(res.data.device_id).slice(0, 8)} hashes=${res.data.vk_hashes?.length ?? 0}`)
    return res.data as VpnConfigPayload
  } catch (e: any) {
    pushLog('Bootstrap', `config FAIL: ${e.response?.data?.detail || e.message}`, 'E')
    return null
  }
}

export async function waitVpnReady(timeoutMs = 90000): Promise<boolean> {
  const electron = (window as any).electronAPI
  if (!electron?.onVpnReady) return true
  return new Promise(resolve => {
    let done = false
    const finish = (ok: boolean) => {
      if (done) return
      done = true
      clearTimeout(timer)
      resolve(ok)
    }
    electron.onVpnReady((ok: boolean) => finish(!!ok))
    const timer = setTimeout(() => finish(false), timeoutMs)
  })
}

let bootstrapActive = false

export function isBootstrapVpnActive(): boolean {
  return bootstrapActive
}

/** Connect bootstrap VPN on login screen — reach backend before Silent login. */
export async function ensureBootstrapVpn(): Promise<boolean> {
  const boot = getBootstrapHash()
  if (!boot) return false
  const electron = (window as any).electronAPI
  if (!electron?.vpnConnect) {
    pushLog('Bootstrap', 'electronAPI.vpnConnect missing', 'E')
    return false
  }

  pushLog('Bootstrap', 'ensureBootstrapVpn start')
  const config = await fetchBootstrapConfig()
  if (!config?.vk_hashes?.length || !config.wg_private_key?.trim()) {
    pushLog('Bootstrap', 'incomplete bootstrap config', 'E')
    return false
  }

  const res = await electron.vpnConnect(config)
  if (res?.error) {
    pushLog('Bootstrap', `vpnConnect error: ${res.error}`, 'E')
    return false
  }
  bootstrapActive = true
  const ok = await waitVpnReady()
  pushLog('Bootstrap', ok ? 'VPN ready' : 'VPN timeout', ok ? 'I' : 'E')
  return ok
}

export async function disconnectBootstrapVpn(): Promise<void> {
  bootstrapActive = false
  await (window as any).electronAPI?.vpnDisconnect?.()
}
