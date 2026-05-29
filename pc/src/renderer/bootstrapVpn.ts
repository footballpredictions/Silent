import api from './api'
import { clearBootstrapHash, getBootstrapHash, type VpnConfigPayload } from './vkConfig'
import { pushLog } from './debugLog'

const PRE_LOGIN_FP_KEY = 'silent_pre_login_fp'
const BOOTSTRAP_SESSION_MS = 2 * 60 * 1000

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
let bootstrapTimeoutTimer: ReturnType<typeof setInterval> | null = null
let bootstrapSessionDeadline = 0
let statusListener: ((msg: string) => void) | null = null

export function setBootstrapStatusListener(fn: ((msg: string) => void) | null) {
  statusListener = fn
}

function notifyStatus(msg: string) {
  statusListener?.(msg)
}

function cancelBootstrapSessionTimeout() {
  if (bootstrapTimeoutTimer) {
    clearInterval(bootstrapTimeoutTimer)
    bootstrapTimeoutTimer = null
  }
}

function startBootstrapSessionTimeout() {
  cancelBootstrapSessionTimeout()
  bootstrapSessionDeadline = Date.now() + BOOTSTRAP_SESSION_MS
  const tick = () => {
    if (!bootstrapActive) {
      cancelBootstrapSessionTimeout()
      return
    }
    const leftSec = Math.floor((bootstrapSessionDeadline - Date.now()) / 1000)
    if (leftSec <= 0) {
      void expireBootstrapSession()
      return
    }
    const mm = Math.floor(leftSec / 60)
    const ss = leftSec % 60
    notifyStatus(
      `Канал готов. Осталось ${mm}:${String(ss).padStart(2, '0')} — войдите или зарегистрируйтесь`,
    )
  }
  tick()
  bootstrapTimeoutTimer = setInterval(tick, 1000)
}

async function expireBootstrapSession() {
  if (!bootstrapActive) return
  pushLog('Bootstrap', `session expired (${BOOTSTRAP_SESSION_MS / 1000}s)`)
  cancelBootstrapSessionTimeout()
  bootstrapActive = false
  clearBootstrapHash()
  await (window as any).electronAPI?.vpnDisconnect?.()
  notifyStatus(
    'Время временного интернета истекло (2 мин). Вставьте хеш заново и нажмите «Подключить для входа».',
  )
}

export function isBootstrapVpnActive(): boolean {
  return bootstrapActive
}

/** Connect bootstrap VPN on login screen — reach backend before Silent login. */
export async function ensureBootstrapVpn(): Promise<boolean> {
  const boot = getBootstrapHash()
  if (!boot) {
    pushLog('Bootstrap', 'no bootstrap hash', 'E')
    return false
  }
  const electron = (window as any).electronAPI
  if (!electron?.vpnConnect) {
    pushLog('Bootstrap', 'electronAPI.vpnConnect missing', 'E')
    return false
  }

  if (bootstrapActive) {
    pushLog('Bootstrap', 'already active')
    return true
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
  if (ok) {
    startBootstrapSessionTimeout()
  } else {
    bootstrapActive = false
    await electron.vpnDisconnect?.()
  }
  return ok
}

export async function disconnectBootstrapVpn(): Promise<void> {
  cancelBootstrapSessionTimeout()
  bootstrapActive = false
  await (window as any).electronAPI?.vpnDisconnect?.()
}
