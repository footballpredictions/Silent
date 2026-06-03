import api from './api'
import { clearBootstrapHash, getBootstrapHash, type VpnConfigPayload } from './vkConfig'
import { pushLog } from './debugLog'
import { buildLocalBootstrapConfig } from './bootstrapVpnConfig'
import { applyBootstrapWorkerCount } from './hashChannelHelper'
import { authStrings as s } from './authStrings'
import { waitVpnReady } from './vpnReady'

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

function applyBootstrapHash(config: VpnConfigPayload, bootHash: string): VpnConfigPayload {
  const hashes = (config.vk_hashes || []).filter(Boolean)
  if (hashes.length > 0) return config
  if (bootHash) return { ...config, vk_hashes: [bootHash] }
  return config
}

export async function fetchBootstrapConfig(): Promise<VpnConfigPayload | null> {
  const boot = getBootstrapHash()
  if (!boot) return null
  const fp = getPreLoginFingerprint()
  pushLog('Bootstrap', `fetch config hash=${boot.slice(0, 12)}…`)
  try {
    const res = await api.post('/api/vpn/bootstrap-config', {
      bootstrap_hash: boot,
      device_type: 'pc',
      device_fingerprint: fp,
    })
    pushLog(
      'Bootstrap',
      `config OK device=${String(res.data.device_id).slice(0, 8)} hashes=${res.data.vk_hashes?.length ?? 0}`,
    )
    return applyBootstrapHash(res.data as VpnConfigPayload, boot)
  } catch (e: any) {
    pushLog('Bootstrap', `config FAIL: ${e.response?.data?.detail || e.message}`, 'E')
    pushLog('Bootstrap', 'bootstrap-config недоступен, локальный конфиг через VK TURN', 'W')
    return applyBootstrapHash(buildLocalBootstrapConfig(boot, fp), boot)
  }
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
  if (bootstrapTimeoutTimer) return
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

/** Restart 2-min countdown if bootstrap VPN is still up (e.g. after remount or failed login). */
export function refreshBootstrapSessionTimer(): void {
  if (!bootstrapActive) return
  cancelBootstrapSessionTimeout()
  startBootstrapSessionTimeout()
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
    refreshBootstrapSessionTimer()
    return true
  }

  pushLog('Bootstrap', 'ensureBootstrapVpn start')
  const config = await fetchBootstrapConfig()
  if (!config?.vk_hashes?.length) {
    pushLog('Bootstrap', 'Нет VK-хеша для bootstrap', 'E')
    notifyStatus('Нет VK-хеша для bootstrap')
    return false
  }

  const bootCfg = applyBootstrapWorkerCount(config, boot)
  pushLog('Bootstrap', `vpnConnect n=${bootCfg.stream_count} hashes=${bootCfg.vk_hashes?.length ?? 0}`)
  const res = await electron.vpnConnect(bootCfg)
  if (res?.error) {
    pushLog('Bootstrap', `vpnConnect error: ${res.error}`, 'E')
    notifyStatus(res.error)
    return false
  }
  bootstrapActive = true

  const ok = await waitVpnReady(90000)
  pushLog('Bootstrap', ok ? 'VPN ready' : 'VPN timeout', ok ? 'I' : 'E')
  if (ok) {
    startBootstrapSessionTimeout()
    return true
  }

  bootstrapActive = false
  await electron.vpnDisconnect?.()
  notifyStatus(s.bootstrapFail)
  return false
}

export async function disconnectBootstrapVpn(): Promise<void> {
  cancelBootstrapSessionTimeout()
  bootstrapActive = false
  await (window as any).electronAPI?.vpnDisconnect?.()
}
