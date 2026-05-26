import api from './api'
import { getBootstrapHash, type VpnConfigPayload } from './vkConfig'

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
  try {
    const res = await api.post('/api/vpn/bootstrap-config', {
      bootstrap_hash: boot,
      device_type: 'pc',
      device_fingerprint: getPreLoginFingerprint(),
    })
    return res.data as VpnConfigPayload
  } catch {
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
  if (!electron?.vpnConnect) return false

  const config = await fetchBootstrapConfig()
  if (!config?.vk_hashes?.length || !config.wg_private_key?.trim()) return false

  const res = await electron.vpnConnect(config)
  if (res?.error) return false
  bootstrapActive = true
  return waitVpnReady()
}

export async function disconnectBootstrapVpn(): Promise<void> {
  bootstrapActive = false
  await (window as any).electronAPI?.vpnDisconnect?.()
}
