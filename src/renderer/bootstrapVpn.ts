import { getBootstrapHash, type VpnConfigPayload } from './vkConfig'
import { pushLog } from './debugLog'
import {
  attachVkCredLaunchParams,
  escalateVkCredSession,
  getEffectiveVkCredStrategy,
  resetVkCredSessionEscalate,
  vkCredStrategyLabel,
} from './vkCredStore'
import { SessionTrace } from './sessionTrace'
import { buildLocalBootstrapConfig } from './bootstrapVpnConfig'
import { applyBootstrapWorkerCount } from './hashChannelHelper'
import { isDebugBuild } from './debugBuild'
import { getDnsOverrideServers } from './dnsPreset'
import { authStrings as s } from './authStrings'
import { waitVpnReady } from './vpnReady'
import { enableTunnelApi, clearTunnelApiBase, setBootstrapApiRouting } from './tunnelApi'
import { syncLoginDataViaTunnel } from './syncBootstrapData'

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
  pushLog('Bootstrap', `local config hash=${boot.slice(0, 12)}… (без public HTTPS)`)
  return applyBootstrapHash(buildLocalBootstrapConfig(boot, fp), boot)
}

let bootstrapActive = false
let bootstrapExpired = false
let bootstrapTimeoutTimer: ReturnType<typeof setInterval> | null = null
let bootstrapSessionDeadline = 0
let statusListener: ((msg: string) => void) | null = null
let lastBootstrapWgAddress: string | null = null
let bootstrapEnsureGeneration = 0

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

function startBootstrapSessionTimeout(forceNewDeadline = false) {
  const now = Date.now()
  if (forceNewDeadline || bootstrapSessionDeadline <= now) {
    bootstrapSessionDeadline = now + BOOTSTRAP_SESSION_MS
  }
  if (bootstrapTimeoutTimer) return
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

function resetBootstrapDeadline() {
  cancelBootstrapSessionTimeout()
  bootstrapSessionDeadline = 0
}

async function expireBootstrapSession() {
  if (!bootstrapActive && !bootstrapExpired) return
  bootstrapEnsureGeneration += 1
  pushLog('Bootstrap', `session expired (${BOOTSTRAP_SESSION_MS / 1000}s)`)
  resetBootstrapDeadline()
  bootstrapActive = false
  bootstrapExpired = true
  setBootstrapApiRouting(false)
  clearTunnelApiBase()
  await (window as any).electronAPI?.vpnDisconnect?.({ fast: true })
  notifyStatus(s.bootstrapExpired)
}

export function isBootstrapVpnActive(): boolean {
  return bootstrapActive
}

export function isBootstrapExpired(): boolean {
  return bootstrapExpired
}

/** Перед login/register — API только через WG (10.66.66.1), не публичный URL. */
export function ensureBootstrapTunnelApi(): boolean {
  if (!bootstrapActive) return false
  enableTunnelApi()
  return true
}

/** Продолжить отсчёт с того же дедлайна (шаг 2 → шаг 1). */
export function refreshBootstrapSessionTimer(): void {
  if (!bootstrapActive) return
  cancelBootstrapSessionTimeout()
  startBootstrapSessionTimeout(false)
}

export function forceNewBootstrapSessionTimer(): void {
  if (!bootstrapActive) return
  cancelBootstrapSessionTimeout()
  startBootstrapSessionTimeout(true)
}

/** Остановить VPN перед полным закрытием приложения с экрана входа. */
export async function shutdownBootstrapBeforeExit(): Promise<void> {
  bootstrapEnsureGeneration += 1
  cancelBootstrapSessionTimeout()
  resetBootstrapDeadline()
  bootstrapActive = false
  setBootstrapApiRouting(false)
  clearTunnelApiBase()
  await (window as any).electronAPI?.vpnDisconnect?.({ fast: true })
}

async function consumeFloodEscalateFlag(): Promise<boolean> {
  try {
    const res = await (window as any).electronAPI?.consumeFloodEscalate?.()
    return !!res?.escalate
  } catch {
    return false
  }
}

/** Connect bootstrap VPN on login screen — reach backend before Silent login. */
export async function ensureBootstrapVpn(): Promise<boolean> {
  if (bootstrapExpired) {
    pushLog('Bootstrap', 'session expired — re-bootstrap blocked')
    notifyStatus(s.bootstrapExpired)
    return false
  }
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
  const runId = ++bootstrapEnsureGeneration

  // Bootstrap всегда VK/WDTT — варианты обхода только после входа (основной VPN).
  SessionTrace.enter('Bootstrap.ensureVpn')
  const config = await fetchBootstrapConfig()
  if (!config?.vk_hashes?.length) {
    pushLog('Bootstrap', 'Нет VK-хеша для bootstrap', 'E')
    notifyStatus('Нет VK-хеша для bootstrap')
    return false
  }

  resetVkCredSessionEscalate()
  await electron.consumeFloodEscalate?.().catch(() => null)

  // vkcalls → (flood/timeout) → auto captcha → manual
  for (let attempt = 0; attempt < 3; attempt++) {
    if (runId !== bootstrapEnsureGeneration) return false

    const bootCfg = attachVkCredLaunchParams(applyBootstrapWorkerCount(config, boot))
    const bootWithDns = isDebugBuild
      ? { ...bootCfg, dns_override: getDnsOverrideServers(), wg_dns: getDnsOverrideServers() }
      : bootCfg
    const modeLabel = vkCredStrategyLabel(getEffectiveVkCredStrategy())
    pushLog(
      'Bootstrap',
      `vpnConnect n=${bootWithDns.stream_count} hashes=${bootWithDns.vk_hashes?.length ?? 0} mode=${modeLabel}`,
    )
    notifyStatus(
      attempt === 0
        ? 'Подключение канала…'
        : `Запасной режим: ${modeLabel}…`,
    )

    const res = await electron.vpnConnect(bootWithDns)
    if (runId !== bootstrapEnsureGeneration) return false
    if (res?.error) {
      pushLog('Bootstrap', `vpnConnect error: ${res.error}`, 'E')
      await consumeFloodEscalateFlag()
      if (escalateVkCredSession()) {
        pushLog('Bootstrap', `escalate → ${vkCredStrategyLabel(getEffectiveVkCredStrategy())}`)
        await electron.vpnDisconnect?.({ fast: true })
        continue
      }
      notifyStatus(res.error)
      return false
    }

    bootstrapActive = true
    bootstrapExpired = false

    const ok = await waitVpnReady(90_000, bootWithDns.stream_count ?? 9, true, bootWithDns.vkAuthMode)
    if (runId !== bootstrapEnsureGeneration || !bootstrapActive) {
      return false
    }
    if (ok) {
      pushLog('Bootstrap', 'VPN ready')
      lastBootstrapWgAddress = bootWithDns.assigned_ip || null
      enableTunnelApi()
      setBootstrapApiRouting(true)
      cancelBootstrapSessionTimeout()
      startBootstrapSessionTimeout(true)
      SessionTrace.mark('Bootstrap.tunnelReady')
      return true
    }

    pushLog('Bootstrap', 'VPN timeout', 'E')
    bootstrapActive = false
    setBootstrapApiRouting(false)
    clearTunnelApiBase()
    await electron.vpnDisconnect?.({ fast: true })

    const flooded = await consumeFloodEscalateFlag()
    if (escalateVkCredSession()) {
      pushLog(
        'Bootstrap',
        `timeout escalate → ${vkCredStrategyLabel(getEffectiveVkCredStrategy())}${flooded ? ' (flood)' : ''}`,
      )
      continue
    }
    break
  }

  notifyStatus(s.bootstrapFail)
  return false
}

/** Профиль и хеши через tunnel (вызывать до disconnect bootstrap). */
export async function prefetchLoginDataViaBootstrap(): Promise<boolean> {
  const { profile, hashesOk, olcrtcOk } = await syncLoginDataViaTunnel()
  pushLog('Bootstrap', `prefetch profile=${!!profile} hashes=${hashesOk} olcrtc=${olcrtcOk}`)
  return !!profile || hashesOk
}

/** Сброс флагов bootstrap без остановки основного VPN. */
export function resetBootstrapRendererState(): void {
  bootstrapEnsureGeneration += 1
  cancelBootstrapSessionTimeout()
  bootstrapActive = false
  setBootstrapApiRouting(false)
  clearTunnelApiBase()
}

export async function disconnectBootstrapVpn(): Promise<void> {
  bootstrapEnsureGeneration += 1
  cancelBootstrapSessionTimeout()
  bootstrapActive = false
  setBootstrapApiRouting(false)
  clearTunnelApiBase()
  await (window as any).electronAPI?.vpnDisconnect?.({ fast: true })
}
