const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, clipboard } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')
const dns = require('dns')
const https = require('https')
const http = require('http')

// Self-signed сервер — как на Android (TrustAllCerts)
app.commandLine.appendSwitch('ignore-certificate-errors')
const {
  stopWireGuardTunnel,
  forceStopWireGuard,
  waitForWdttProxy,
  waitForUdpPortFree,
  waitForTunnelDown,
  isProcessElevated,
  isTunnelUp,
  isServiceRunning,
  isTunnelUpAsync,
  isServiceRunningAsync,
  buildWgConfigFromApi,
  applyWireGuardConfig,
  addServerBypassRoutes,
  capturePhysicalGateway,
  normalizeWgConfText,
  waitWgStopIdle,
  prepareRuntimeDir,
} = require('./vpn/wireguard')
const { solveVkCaptcha, cancelCaptchaSolve } = require('./vk/captchaWebView')
const { resolveVkExcludeIps, warmVkExcludeIps, invalidateVkExcludeCache } = require('./vpn/vkNetworkExcludes')
const buildFlags = require('./buildFlags')
const { verifyWdttIntegrity, softTamperHints } = require('./integrity')
const { effectiveConnectWorkers, WORKERS_PER_GROUP } = require('./workerLimits')

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

const isDev = process.env.NODE_ENV === 'development'
const isDebugBuild = !!buildFlags.DEBUG_BUILD || process.env.DEBUG_BUILD === '1' || !app.isPackaged
const WIN_WIDTH = 265
const WIN_HEIGHT = 606

let mainWindow = null
let tray = null
let isQuitting = false
let wdttProcess = null
let wgApplied = false
let pendingVkDeepLink = null
let pendingRefDeepLink = null
let vpnSessionActive = false
let connectStartedAtMs = 0
let pausedForNetwork = false
let transportSwitching = false
let lastVpnConnectConfig = null
let activeWorkerCount = 0
let lastStatsLogToUiAt = 0
let sessionTargetWorkers = 63
let sessionDnsOverride = null
let tunnelReadySent = false
let wdttStartedAtMs = 0
let networkMonitor = null
let wdttRelaunchTimer = null
let vpnConnectInFlight = false
let tunnelReadyPollTimer = null
let vpnBootstrapMode = false
let wgCredPhase = false
let expectedCredGroups = 1
let credGroupsResolved = 0
let fullTunnelUpgradeTimer = null
let wgFullTunnelUpgradeInFlight = false
/** После subnet→full reinstall маршруты мигают ~несколько секунд (EACCES/ECONNABORTED). */
let wgRouteSettleUntil = 0
let wdttGeneration = 0
let wdttReplacing = false
let captchaSession = 0
let captchaInProgress = false
let captchaQueue = []
let captchaQueueDrainRunning = false
/** После капчи не спамить public HTTPS пока WG/bypass не устаканятся. */
let apiQuietUntil = 0
/** GETCONF во время капчи — поднять WG сразу после CAPTCHA_RESULT. */
let pendingWgAfterCaptcha = false
/** Выставляется внутри vpnConnect → requestApplyFromFile. */
let requestApplyWgAfterCaptcha = null
/** Flood control (VK error 9) — renderer каскад vkcalls→auto→manual. */
let vkFloodEscalatePending = false

function noteVkFloodFromLog(line) {
  const m = String(line || '').toLowerCase()
  if (
    m.includes('legacy_escalate_captcha') ||
    m.includes('flood_escalate_captcha') ||
    m.includes('flood control') ||
    m.includes('kind=flood')
  ) {
    vkFloodEscalatePending = true
  }
}

function consumeVkFloodEscalate() {
  const escalate = vkFloodEscalatePending
  vkFloodEscalatePending = false
  return { escalate }
}

const SERVER_IP_FALLBACK = '132.243.234.162'
let sessionExcludeIPs = [SERVER_IP_FALLBACK]
let bypassRefreshTimer = null

function normalizeServerIp(raw) {
  const s = String(raw || '').trim()
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(s)) return s
  return SERVER_IP_FALLBACK
}

const { createNetworkMonitor } = require('./vpn/networkRecovery')
const { createSessionTrace } = require('./sessionTrace')
const { parseLibclientLine } = require('./libclientLogParser')
const { parseHashFailureFromLine, resetCaptchaHits } = require('./hashFailureFromLog')

const ZERO_WORKERS_RELAUNCH_MS = 90_000
let sessionVkHashes = []
const groupHashPrefix = new Map()
let zeroWorkersSinceMs = 0
let zeroWorkersWatchdogTimer = null

function resolveAssetPath(relativePath) {
  const rel = relativePath.replace(/^[/\\]+/, '')
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, rel)]
    : [path.join(__dirname, '../../', rel), path.join(process.resourcesPath, rel)]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return candidates[0]
}

let sessionTrace = null
function trace() {
  if (!sessionTrace) sessionTrace = createSessionTrace(sendDebugLog)
  return sessionTrace
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', (_, argv) => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.show()
      mainWindow.focus()
    }
    const url = argv.find(a => typeof a === 'string' && a.startsWith('silentvpn://'))
    if (url) handleDeepLink(url)
  })
}

function handleDeepLink(url) {
  if (!url || typeof url !== 'string' || !url.startsWith('silentvpn://')) return
  try {
    const u = new URL(url)
    if (u.hostname === 'vk-linked') {
      const boot = u.searchParams.get('boot') || ''
      const vkRaw = u.searchParams.get('vk')
      const vk = vkRaw ? parseInt(vkRaw, 10) : null
      const payload = { boot, vk: Number.isFinite(vk) ? vk : null }
      if (mainWindow && !mainWindow.isDestroyed()) {
        const send = () => {
          mainWindow.webContents.send('vk-deep-link', payload)
          mainWindow.show()
          mainWindow.focus()
        }
        if (mainWindow.webContents.isLoading()) {
          pendingVkDeepLink = payload
        } else {
          send()
        }
      } else {
        pendingVkDeepLink = payload
      }
      return
    }
    if (u.hostname === 'ref') {
      const code = (u.searchParams.get('code') || '').trim()
      if (!code) return
      const payload = { code }
      if (mainWindow && !mainWindow.isDestroyed()) {
        const send = () => {
          mainWindow.webContents.send('ref-deep-link', payload)
          mainWindow.show()
          mainWindow.focus()
        }
        if (mainWindow.webContents.isLoading()) {
          pendingRefDeepLink = payload
        } else {
          send()
        }
      } else {
        pendingRefDeepLink = payload
      }
    }
  } catch {}
}

if (process.platform === 'win32') {
  const launchUrl = process.argv.find(a => typeof a === 'string' && a.startsWith('silentvpn://'))
  if (launchUrl) handleDeepLink(launchUrl)
}

app.on('open-url', (event, url) => {
  event.preventDefault()
  handleDeepLink(url)
})

function createWindow() {
  mainWindow = new BrowserWindow({
    width: WIN_WIDTH,
    height: WIN_HEIGHT,
    minWidth: WIN_WIDTH,
    minHeight: WIN_HEIGHT,
    maxWidth: WIN_WIDTH,
    maxHeight: WIN_HEIGHT,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    frame: false,
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
    icon: resolveAssetPath('assets/icon.png'),
    title: 'Silent VPN',
    // Не показывать пустое окно, пока renderer не готов (белый экран).
    show: false,
  })

  mainWindow.once('ready-to-show', () => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show()
      mainWindow.focus()
    }
  })
  // Fallback: если ready-to-show завис — всё равно показать.
  setTimeout(() => {
    if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) {
      mainWindow.show()
    }
  }, 2500)

  if (!app.isPackaged && process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:3001')
  } else {
    mainWindow.loadFile(path.join(__dirname, '../../dist/renderer/index.html'))
  }

  mainWindow.webContents.on('did-finish-load', () => {
    if (pendingVkDeepLink) {
      mainWindow.webContents.send('vk-deep-link', pendingVkDeepLink)
      pendingVkDeepLink = null
      mainWindow.show()
      mainWindow.focus()
    }
    if (pendingRefDeepLink) {
      mainWindow.webContents.send('ref-deep-link', pendingRefDeepLink)
      pendingRefDeepLink = null
      mainWindow.show()
      mainWindow.focus()
    }
  })
  mainWindow.on('close', (e) => {
    if (!isQuitting && tray) {
      e.preventDefault()
      mainWindow.hide()
    }
  })
}

function createTray() {
  let icon = nativeImage.createFromPath(resolveAssetPath('assets/tray.png'))
  if (icon.isEmpty()) icon = nativeImage.createFromPath(resolveAssetPath('assets/icon.png'))
  if (icon.isEmpty()) {
    console.error('[Tray] иконка не найдена (assets/tray.png)')
    return
  }
  icon = icon.resize({ width: 16, height: 16 })
  tray = new Tray(icon)
  tray.setToolTip('Silent VPN')
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Открыть Silent VPN', click: () => { mainWindow.show(); mainWindow.focus() } },
    { type: 'separator' },
    { label: 'Выход', click: () => quitAppFully() },
  ])
  tray.setContextMenu(contextMenu)
  tray.on('click', () => {
    if (mainWindow.isVisible()) mainWindow.hide()
    else { mainWindow.show(); mainWindow.focus() }
  })
}

function sendDebugLog(payload) {
  if (!isDebugBuild) return
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('debug-log', payload)
  }
}

/** Батч IPC логов: при наборе 36 воркеров иначе десятки send/сек → «Не отвечает». */
const WDTT_LOG_FLUSH_MS = 120
let wdttLogPending = new Map()
let wdttLogFlushTimer = null

function flushWdttLogBatch() {
  wdttLogFlushTimer = null
  if (!wdttLogPending.size) return
  if (!mainWindow || mainWindow.isDestroyed()) {
    wdttLogPending.clear()
    return
  }
  const batch = Array.from(wdttLogPending.values())
  wdttLogPending.clear()
  mainWindow.webContents.send('wdtt-log-batch', batch)
}

function sendWdttLog(entry) {
  if (!isDebugBuild || !entry?.key) return
  const prev = wdttLogPending.get(entry.key)
  if (prev) {
    wdttLogPending.set(entry.key, {
      ...entry,
      _hits: (prev._hits || 1) + 1,
    })
  } else {
    wdttLogPending.set(entry.key, { ...entry, _hits: 1 })
  }
  if (entry.isError) {
    if (wdttLogFlushTimer) {
      clearTimeout(wdttLogFlushTimer)
      wdttLogFlushTimer = null
    }
    flushWdttLogBatch()
    return
  }
  if (!wdttLogFlushTimer) {
    wdttLogFlushTimer = setTimeout(flushWdttLogBatch, WDTT_LOG_FLUSH_MS)
  }
}

function sendHashFailureReport(payload) {
  if (!payload?.hash || mainWindow?.isDestroyed()) return
  mainWindow.webContents.send('hash-failure', payload)
}

function resetHashFailureSessionState() {
  sessionVkHashes = []
  groupHashPrefix.clear()
  resetCaptchaHits()
  zeroWorkersSinceMs = 0
  if (zeroWorkersWatchdogTimer) {
    clearInterval(zeroWorkersWatchdogTimer)
    zeroWorkersWatchdogTimer = null
  }
}

function hashFailureCtx() {
  return {
    sessionVkHashes,
    groupHashPrefix,
    tunnelReady: wgApplied && tunnelReadySent,
  }
}

function maybeReportHashFailureFromLine(line) {
  const failure = parseHashFailureFromLine(line, hashFailureCtx())
  if (failure) sendHashFailureReport(failure)
}

function startZeroWorkersWatchdog() {
  if (zeroWorkersWatchdogTimer) clearInterval(zeroWorkersWatchdogTimer)
  zeroWorkersSinceMs = 0
  zeroWorkersWatchdogTimer = setInterval(() => {
    if (!vpnSessionActive || !wgApplied || !tunnelReadySent || transportSwitching) {
      zeroWorkersSinceMs = 0
      return
    }
    if (!isWdttAlive()) return
    if (activeWorkerCount > 0) {
      zeroWorkersSinceMs = 0
      return
    }
    const now = Date.now()
    if (!zeroWorkersSinceMs) zeroWorkersSinceMs = now
    else if (now - zeroWorkersSinceMs >= ZERO_WORKERS_RELAUNCH_MS) {
      zeroWorkersSinceMs = 0
      const hash = sessionVkHashes[0]
      if (hash && hash.length >= 6) {
        sendHashFailureReport({
          hash,
          errorType: 'no_connections',
          message: '0 active workers for 90s',
        })
      }
      sendLog('[VPN] 0 активных воркеров 90с — перезапуск wdtt…')
      transportSwitching = true
      scheduleWdttRelaunch(800)
    }
  }, 5000)
}

function sendLog(line) {
  const trimmed = String(line || '').trim()
  if (!trimmed) return

  noteVkFloodFromLog(trimmed)

  const parsed = parseLibclientLine(trimmed)
  if (parsed) {
    sendWdttLog(parsed)
    return
  }

  // parseLibclientLine → null: ретраи / DTLS flood / WRAP — не слать в UI
  if (/\[ВОРКЕР #|\[СЕССИЯ #|WRAP_AUTH_TIMEOUT|\[DTLS\]|Рукопожатие|Соединение установлено|\[READY\]/i.test(trimmed)) return

  // Сильный шум из VK Auth (десятки строк/сек) забивает IPC и фризит UI.
  if (/\[VK Auth\]\s+(Trying credentials|Failed with|Both VK credentials failed|Success with)/i.test(trimmed)) {
    return
  }

  if (/^\[WG\]|^\[VPN\]|^\[Update\]/.test(trimmed)) {
    const isError = /error|ошиб|fail|таймаут/i.test(trimmed)
    const tag = trimmed.startsWith('[WG]') ? 'WireGuard' : 'VPN'
    sendWdttLog({
      key: `sys_${tag}_${trimmed.slice(0, 36).replace(/\d+/g, '#')}`,
      message: trimmed,
      priority: isError ? 99 : 2,
      isError,
    })
    return
  }

  if (
    /\[КЛИЕНТ\]|\[STREAM|\[ГРУППА|\[VK Auth\]|FATAL|GETCONF|CAPTCHA|ошибка|error|timeout|зарегистрирован/i.test(trimmed)
  ) {
    const isError = /error|ошиб|fail|timeout|FATAL|FLOOD_ESCALATE/i.test(trimmed)
    sendWdttLog({
      key: `raw_${trimmed.slice(0, 28).replace(/\d+/g, '#')}`,
      message: trimmed,
      priority: isError ? 99 : 2,
      isError,
    })
  }
}

function clearFullTunnelUpgradeTimer() {
  if (fullTunnelUpgradeTimer) {
    clearTimeout(fullTunnelUpgradeTimer)
    fullTunnelUpgradeTimer = null
  }
}

function quitAppFully() {
  if (isQuitting) return
  isQuitting = true
  try {
    if (tray && !tray.isDestroyed()) {
      tray.destroy()
      tray = null
    }
  } catch { /* ignore */ }
  try {
    cleanupVpn()
  } catch { /* ignore */ }
  try {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.removeAllListeners('close')
      mainWindow.destroy()
    }
  } catch { /* ignore */ }
  setImmediate(() => {
    try { app.exit(0) } catch { app.quit() }
  })
}

function cleanupVpn() {
  try {
    const { clearActiveExcludedExePaths } = require('./apps/vpnAppExclusions')
    void clearActiveExcludedExePaths(sendLog)
  } catch { /* ignore */ }
  clearTelegramWarmupTimers()
  resetHashFailureSessionState()
  vpnBootstrapMode = false
  wgCredPhase = false
  expectedCredGroups = 1
  credGroupsResolved = 0
  wgFullTunnelUpgradeInFlight = false
  wgRouteSettleUntil = 0
  clearFullTunnelUpgradeTimer()
  vpnSessionActive = false
  pausedForNetwork = false
  transportSwitching = false
  lastVpnConnectConfig = null
  activeWorkerCount = 0
  if (wdttRelaunchTimer) {
    clearTimeout(wdttRelaunchTimer)
    wdttRelaunchTimer = null
  }
  networkMonitor?.stop()
  networkMonitor = null
  cancelCaptchaSolve()
  captchaInProgress = false
  captchaQueue = []
  captchaQueueDrainRunning = false
  if (wdttProcess) {
    try { wdttProcess.kill() } catch {}
    wdttProcess = null
  }
  // Не await — cleanupVpn синхронный; async stop не блокирует main/UI
  void stopWireGuardTunnel(isDev, __dirname, sendLog, sessionExcludeIPs)
  clearBypassRefresh()
  wgApplied = false
  tunnelReadySent = false
  clearTunnelReadyPoll()
}

function isWdttAlive() {
  if (!wdttProcess) return false
  try {
    return wdttProcess.exitCode === null && !wdttProcess.killed
  } catch {
    return false
  }
}

const TRANSPORT_RESTART_GRACE_MS = 90_000

function isTransportHealthy() {
  return wgApplied && activeWorkerCount >= minWorkersForTunnelReady(vpnBootstrapMode) && isWdttAlive()
}

function clearTunnelReadyPoll() {
  if (tunnelReadyPollTimer) {
    clearInterval(tunnelReadyPollTimer)
    tunnelReadyPollTimer = null
  }
}

function scheduleTunnelReadyPoll(sendLogFn) {
  clearTunnelReadyPoll()
  let attempts = 0
  tunnelReadyPollTimer = setInterval(() => {
    attempts += 1
    ensureVpnReadyEvent(sendLogFn)
    if (tunnelReadySent || attempts >= 120) clearTunnelReadyPoll()
  }, 500)
}

/** Legacy: full после N воркеров (сейчас main сразу full после GETCONF). */
const FULL_TUNNEL_TARGET_CAP = 9

const FALLBACK_BACKEND_IP = SERVER_IP_FALLBACK

/**
 * IP вне WG через host-route bypass (не через AllowedIPs-split):
 * Улей/peer + VK API/login/TURN — иначе WDTT auth идёт в туннель / kill-switch.
 */
async function collectExcludeIPs(config) {
  const ips = new Set([SERVER_IP_FALLBACK])
  const peer = normalizeServerIp(config?.server_ip)
  if (peer) ips.add(peer)
  try {
    const vkIps = await resolveVkExcludeIps()
    for (const ip of vkIps) ips.add(ip)
  } catch { /* DNS fail — остаётся peer/API */ }
  return [...ips]
}

function clearBypassRefresh() {
  if (bypassRefreshTimer) {
    clearInterval(bypassRefreshTimer)
    bypassRefreshTimer = null
  }
}

function scheduleBypassRefresh(sendLogFn) {
  clearBypassRefresh()
  bypassRefreshTimer = setInterval(() => {
    if (!wgApplied || vpnBootstrapMode) return
    void addServerBypassRoutes(sessionExcludeIPs, () => {})
  }, 90_000)
}

function minCredGroupsForFullTunnel(total) {
  return Math.min(3, Math.max(1, total))
}

function fullTunnelTargetWorkers() {
  if (vpnBootstrapMode) return 1
  const target = Math.max(1, sessionTargetWorkers || 1)
  if (target <= WORKERS_PER_GROUP) return target
  return Math.min(target, FULL_TUNNEL_TARGET_CAP)
}

function minWorkersForTunnelReady(isBootstrap = false) {
  if (isBootstrap || vpnBootstrapMode) return 1
  // UI «Подключено» после WG + 1 воркер (как Android); full tunnel ≥27 — в фоне.
  return 1
}

function isVpnReadyForUi() {
  if (tunnelReadySent) return true
  // WG + ≥1 воркер: api-early без GETCONF давал «Подключено» при мёртвом 10.66.66.1
  return wgApplied && activeWorkerCount >= 1 && isWdttAlive()
}

async function stopWdttForReplace(sendLogFn, reason = 'replace') {
  const proc = wdttProcess
  if (!proc) return
  wdttReplacing = true
  sendLogFn?.(`[VPN] остановка wdtt (${reason})…`)
  wdttProcess = null
  try {
    proc.kill()
  } catch { /* ignore */ }
  await waitForUdpPortFree('127.0.0.1', 9000, 10_000, sendLogFn)
  await sleep(400)
  wdttReplacing = false
}

function ensureVpnReadyEvent(sendLogFn) {
  if (tunnelReadySent || !isVpnReadyForUi()) return
  tunnelReadySent = true
  clearTunnelReadyPoll()
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('vpn-ready', { ok: true, bootstrap: vpnBootstrapMode })
  }
  sendLogFn?.(`[VPN] tunnel ready (WG + ${activeWorkerCount}/${sessionTargetWorkers} workers)`)
  // Прогрев DC/CDN Telegram: сразу + повтор когда воркеры догонят (превью/медиа).
  if (!vpnBootstrapMode) {
    void warmupTelegramTcp(sendLogFn)
    scheduleTelegramWarmupRetries(sendLogFn)
  }
}

let telegramWarmupTimers = []

function clearTelegramWarmupTimers() {
  for (const t of telegramWarmupTimers) clearTimeout(t)
  telegramWarmupTimers = []
}

function scheduleTelegramWarmupRetries(sendLogFn) {
  clearTelegramWarmupTimers()
  // Первый ready часто при части воркеров; превью Telegram любит «пустой» путь.
  for (const ms of [4000, 12000]) {
    telegramWarmupTimers.push(setTimeout(() => {
      if (!vpnSessionActive || vpnBootstrapMode) return
      void warmupTelegramTcp(sendLogFn)
    }, ms))
  }
}

/** TCP/DNS к DC + CDN Telegram — превью и media чувствительнее файлов. */
function warmupTelegramTcp(sendLogFn) {
  const net = require('net')
  const dns = require('dns')
  const targets = [
    // DC1–5 (типичные egress для desktop TG)
    { host: '149.154.175.50', port: 443 },
    { host: '149.154.175.100', port: 443 },
    { host: '149.154.167.51', port: 443 },
    { host: '149.154.167.91', port: 443 },
    { host: '91.108.56.165', port: 443 },
    { host: '91.108.4.134', port: 443 },
    { host: '91.108.8.68', port: 443 },
    // MTProto часто 5222 (превью/медиа), не только 443
    { host: '149.154.167.51', port: 5222 },
    { host: '149.154.175.50', port: 5222 },
    { host: '91.108.56.165', port: 5222 },
    { host: 'api.telegram.org', port: 443 },
  ]
  sendLogFn?.(`[Apps] warmup Telegram DC/CDN (TCP, workers=${activeWorkerCount})…`)
  for (const t of targets) {
    try {
      const sock = net.connect({ host: t.host, port: t.port, family: 4 }, () => {
        try { sock.destroy() } catch { /* ignore */ }
      })
      sock.setTimeout(5000, () => {
        try { sock.destroy() } catch { /* ignore */ }
      })
      sock.on('error', () => {})
    } catch { /* ignore */ }
  }
  const names = [
    'api.telegram.org',
    'telegram.org',
    'core.telegram.org',
    'cdn1.telegram.org',
    'cdn2.telegram.org',
    'cdn3.telegram.org',
    'cdn4.telegram.org',
    'venus.web.telegram.org',
    'flora.web.telegram.org',
  ]
  for (const name of names) {
    try { dns.lookup(name, { family: 4 }, () => {}) } catch { /* ignore */ }
  }
}

function pauseWdtt(reason) {
  if (!vpnSessionActive || !wgApplied || pausedForNetwork) return
  sendLog(`[VPN] ${reason} — pause wdtt (WG остаётся)`)
  pausedForNetwork = true
  transportSwitching = true
  if (wdttProcess) {
    try { wdttProcess.kill() } catch {}
    wdttProcess = null
  }
  activeWorkerCount = 0
}

function restoreTransport(reason) {
  if (!vpnSessionActive || !lastVpnConnectConfig) return
  const { hasUnderlyingInternet } = require('./vpn/networkRecovery')
  if (!hasUnderlyingInternet()) return
  if (isTransportHealthy()) {
    pausedForNetwork = false
    return
  }
  sendLog(`[VPN] Восстановление транспорта (${reason}), workers=${activeWorkerCount}`)
  pausedForNetwork = false
  scheduleWdttRelaunch(800)
}

function scheduleWdttRelaunch(delayMs = 800) {
  if (!vpnSessionActive || !lastVpnConnectConfig) return
  if (wdttProcess && isWdttAlive()) return
  if (wdttRelaunchTimer) clearTimeout(wdttRelaunchTimer)
  wdttRelaunchTimer = setTimeout(() => {
    wdttRelaunchTimer = null
    if (!vpnSessionActive || wdttProcess || !lastVpnConnectConfig) return
    transportSwitching = true
    sendLog('[VPN] Перезапуск wdtt-client…')
    trace().mark('Main.wdttRelaunch')
    beginWdttSession(lastVpnConnectConfig, { switching: true }).catch(e => {
      sendLog('[VPN] relaunch failed: ' + (e.message || e))
    })
  }, delayMs)
}

function startNetworkMonitor() {
  const state = {
    get connectStartedAtMs() { return connectStartedAtMs },
    get wgApplied() { return wgApplied },
    get vpnSessionActive() { return vpnSessionActive },
    get pausedForNetwork() { return pausedForNetwork },
    set pausedForNetwork(v) { pausedForNetwork = v },
    get activeWorkerCount() { return activeWorkerCount },
    get wdttStartedAtMs() { return wdttStartedAtMs },
  }
  networkMonitor?.stop()
  networkMonitor = createNetworkMonitor(state, {
    pauseWdtt,
    restoreTransport,
    isTransportHealthy,
  })
  networkMonitor.start()
}

async function cleanupVpnAsync() {
  cleanupVpn()
  await waitForTunnelDown(15000, sendLog)
  await sleep(500)
}

async function fastDisconnectVpn() {
  // cleanupVpn гасит wdtt и стартует stopWireGuardTunnel в фоне.
  // Не ждём uninstall/sc — иначе тумблер «мёртвый» 10–20с.
  cleanupVpn()
}

function writeCaptchaResult(session, result) {
  if (session !== captchaSession) return
  const proc = wdttProcess
  if (!proc || !proc.stdin || proc.killed) return
  try {
    proc.stdin.write(`CAPTCHA_RESULT|${result}\n`)
    proc.stdin.write('') // flush hint
  } catch (e) {
    sendLog(`[КАПЧА] не удалось отправить результат: ${e.message || e}`)
  }
}

function scheduleCaptchaSolve(lineTrim) {
  captchaInProgress = true
  captchaQueue.push(lineTrim)
  void drainCaptchaQueue()
}

async function drainCaptchaQueue() {
  if (captchaQueueDrainRunning) return
  captchaQueueDrainRunning = true
  try {
    while (captchaQueue.length > 0) {
      const lineTrim = captchaQueue.shift()
      await runCaptchaSolve(lineTrim)
    }
  } finally {
    captchaQueueDrainRunning = false
    captchaInProgress = false
    apiQuietUntil = Date.now() + 10_000
    if (pendingWgAfterCaptcha) {
      pendingWgAfterCaptcha = false
      sendLog('[WG] капча готова — поднимаем туннель')
      if (typeof requestApplyWgAfterCaptcha === 'function') {
        requestApplyWgAfterCaptcha()
      }
    } else if (wgApplied) {
      void ensurePublicApiBypass(sendLog)
    }
  }
}

async function runCaptchaSolve(lineTrim) {
  const parts = lineTrim.split('|')
  if (parts.length < 3) return
  const mode = (parts[1] || 'auto').toLowerCase()
  const redirectUri = parts[2] || ''
  if (!redirectUri) return

  captchaInProgress = true
  const session = ++captchaSession
  const { normalizeCaptchaRedirectUri } = require('./vk/captchaRedirectUri')
  const uriForLog = normalizeCaptchaRedirectUri(redirectUri)
  sendLog(`[КАПЧА] ${mode === 'manual' ? 'ручное окно' : 'авто'} (${uriForLog.slice(0, 48)}…)`)

  let token = ''
  try {
    // Manual only: лёгкий bypass refresh (не блокируем auto DNS-ожиданием).
    if (mode === 'manual' && wgApplied && !vpnBootstrapMode) {
      try {
        invalidateVkExcludeCache()
        const vkIps = await resolveVkExcludeIps()
        sessionExcludeIPs = [...new Set([...(sessionExcludeIPs || []), SERVER_IP_FALLBACK, ...vkIps])]
        await capturePhysicalGateway(sendLog)
        await addServerBypassRoutes(sessionExcludeIPs, sendLog)
      } catch { /* ignore */ }
    }
    token = await solveVkCaptcha(redirectUri, mode)
    if (session !== captchaSession) return
    sendLog('[КАПЧА] Решена ✓')
    writeCaptchaResult(session, token)
  } catch (e) {
    if (session !== captchaSession) return
    const msg = e?.message || String(e)
    if (msg === 'slider_detected' && mode !== 'manual') {
      try {
        token = await solveVkCaptcha(redirectUri, 'manual')
        if (session !== captchaSession) return
        sendLog('[КАПЧА] Решена вручную ✓')
        writeCaptchaResult(session, token)
        return
      } catch (e2) {
        writeCaptchaResult(session, `error:${e2?.message || e2}`)
        sendLog(`[КАПЧА] ${e2?.message || e2}`)
        return
      }
    }
    writeCaptchaResult(session, `error:${msg}`)
    sendLog(`[КАПЧА] ${msg}`)
  }
}

function wdttExePath() {
  const p = isDev
    ? path.join(__dirname, '../../resources/wdtt-client.exe')
    : path.join(process.resourcesPath, 'wdtt-client.exe')
  return p
}

ipcMain.handle('list-installed-apps', async () => {
  try {
    const { listInstalledApps } = require('./apps/listInstalledApps')
    const apps = listInstalledApps()
    const withIcon = apps.filter(a => a.icon).length
    sendLog(`[Apps] ярлыки: ${apps.length}, иконок: ${withIcon}`)
    return apps
  } catch (e) {
    sendLog(`[Apps] ошибка списка: ${e?.message || e}`)
    return []
  }
})

ipcMain.handle('save-app-exclusions', (_, payload) => {
  try {
    const { saveExclusionsState, defaultStatePath } = require('./apps/exclusionsState')
    const { applyAppExclusionsForSession, clearActiveExcludedExePaths } = require('./apps/vpnAppExclusions')
    const filePath = defaultStatePath(app.getPath('userData'))
    const selectedIds = Array.isArray(payload?.selectedIds) ? payload.selectedIds : []
    const appsList = Array.isArray(payload?.apps) ? payload.apps : []
    const saved = saveExclusionsState({ filePath, selectedIds, apps: appsList })
    sendLog(`[Apps] сохранены исключения: ${saved.exePaths.length} exe`)
    // VPN уже поднят — сразу перезапустить bypass-монитор
    if (wgApplied && !vpnBootstrapMode) {
      if (saved.exePaths.length) {
        applyAppExclusionsForSession(saved.exePaths, sendLog)
      } else {
        void clearActiveExcludedExePaths(sendLog)
      }
    }
    return { ok: true, exePaths: saved.exePaths }
  } catch (e) {
    sendLog(`[Apps] save exclusions: ${e?.message || e}`)
    return { ok: false, exePaths: [] }
  }
})

ipcMain.handle('get-app-exclusions', () => {
  const { loadExclusionsState, defaultStatePath } = require('./apps/exclusionsState')
  return loadExclusionsState(defaultStatePath(app.getPath('userData')))
})

ipcMain.handle('warmup-telegram-path', async () => {
  warmupTelegramTcp(sendLog)
  return true
})

ipcMain.handle('window-minimize', () => mainWindow?.minimize())
ipcMain.handle('window-close', () => mainWindow?.hide())
ipcMain.handle('app-quit', () => {
  quitAppFully()
  return true
})
async function ensureNipIoBypassRoutes(sendLogFn = sendLog) {
  if (!wgApplied || vpnBootstrapMode) return
  const ips = new Set([SERVER_IP_FALLBACK, ...(sessionExcludeIPs || [])])
  try {
    const resolved = await resolve4WithTimeout('132-243-234-162.nip.io', 2000)
    for (const ip of resolved || []) {
      if (ip) ips.add(ip)
    }
  } catch { /* DNS fail — остаётся SERVER_IP */ }
  const list = [...ips]
  sessionExcludeIPs = [...new Set([...(sessionExcludeIPs || []), ...list])]
  await capturePhysicalGateway(sendLogFn)
  await addServerBypassRoutes(sessionExcludeIPs, sendLogFn)
  await sleep(400)
}

/**
 * Перед public HTTPS (fallback с туннеля / браузер): маршрут к VPS мимо WG.
 * Без этого full-tunnel + hairpin → ETIMEDOUT на nip.io и на 132.243.234.162:443.
 * Не дёргать bypass чаще раза в 3с — иначе гонка маршрутов.
 */
let lastPublicBypassAt = 0
async function ensurePublicApiBypass(sendLogFn = sendLog) {
  if (!wgApplied || vpnBootstrapMode) return
  const now = Date.now()
  if (now - lastPublicBypassAt < 3000) return
  lastPublicBypassAt = now
  try {
    await ensureNipIoBypassRoutes(sendLogFn)
  } catch (e) {
    sendLogFn?.(`[API] public bypass: ${e?.message || e}`)
  }
}

function resolve4WithTimeout(host, ms = 2000) {
  return Promise.race([
    dns.promises.resolve4(host),
    new Promise((_, reject) => setTimeout(() => reject(new Error('dns timeout')), ms)),
  ])
}

/** YuMoney/success page must leave full-tunnel VPN, иначе оплата в браузере зависает. */
async function ensurePaymentBypassRoutes(url, sendLogFn = sendLog) {
  if (!wgApplied || vpnBootstrapMode) return
  const hosts = new Set()
  try {
    const u = new URL(String(url || ''))
    if (u.hostname) hosts.add(u.hostname)
  } catch { /* ignore */ }
  hosts.add('yoomoney.ru')
  hosts.add('money.yandex.ru')
  hosts.add('132-243-234-162.nip.io')
  const extra = [SERVER_IP_FALLBACK]
  await Promise.all([...hosts].map(async (host) => {
    try {
      const ips = await resolve4WithTimeout(host, 2000)
      for (const ip of ips) {
        if (ip && !sessionExcludeIPs.includes(ip) && !extra.includes(ip)) extra.push(ip)
      }
    } catch {
      /* DNS fail/timeout — всё равно откроем браузер */
    }
  }))
  try {
    await capturePhysicalGateway(sendLogFn)
    await addServerBypassRoutes([...sessionExcludeIPs, ...extra], sendLogFn)
    sessionExcludeIPs = [...new Set([...(sessionExcludeIPs || []), ...extra])]
    await sleep(300)
  } catch (e) {
    sendLogFn('[payment-bypass] ' + (e && e.message ? e.message : e))
  }
}

ipcMain.handle('open-external', async (_, url) => {
  try {
    if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) {
      sendLog('[open-external] invalid url')
      return false
    }
    if (/132-243-234-162\.nip\.io|132\.243\.234\.162|yoomoney\.ru|money\.yandex\.ru/i.test(url)) {
      await ensurePaymentBypassRoutes(url)
    }
    await shell.openExternal(url)
    return true
  } catch (e) {
    sendLog('[open-external] fail: ' + (e && e.message ? e.message : e))
    return false
  }
})
/**
 * Админка в системном браузере — всегда главная публичная ссылка nip.io.
 * Tunnel 10.66.66.1 для /dashboard → 404 (Host guard: только ADMIN_PUBLIC_HOST).
 * При VPN перед открытием — bypass nip.io, иначе full-tunnel / whitelist режут браузер.
 */
function resolveAdminPanelUrl() {
  // Строка, не UPDATE_PUBLIC_BASE: константа объявлена ниже по файлу.
  return 'https://132-243-234-162.nip.io/dashboard'
}

ipcMain.handle('get-admin-panel-url', () => resolveAdminPanelUrl())
ipcMain.handle('open-admin-panel', async () => {
  const url = resolveAdminPanelUrl()
  try {
    if (vpnSessionActive || wgApplied) {
      await ensurePublicApiBypass(sendLog)
      sendLog(`[Admin] public nip.io (+ bypass) → ${url}`)
    } else {
      sendLog(`[Admin] public nip.io → ${url}`)
    }
  } catch (e) {
    sendLog(`[Admin] bypass warn: ${e?.message || e} — всё равно ${url}`)
  }
  await shell.openExternal(url)
  return url
})
ipcMain.handle('get-platform', () => process.platform)

ipcMain.handle('clipboard-write', (_, text) => {
  clipboard.writeText(String(text ?? ''))
  return true
})

ipcMain.handle('vk-guest-bootstrap', async (_, authUrl) => {
  const { runVkAndroidOAuth } = require('./vk/oauth')
  const { createCallHash, resolveUserId } = require('./vk/calls')
  const { accessToken, userId } = await runVkAndroidOAuth(authUrl)
  const hash = await createCallHash(accessToken)
  const uid = userId > 0 ? userId : await resolveUserId(accessToken)
  return { access_token: accessToken, vk_user_id: uid, bootstrap_hash: hash }
})

async function beginWdttSession(config, { switching = false } = {}) {
  vpnBootstrapMode = !!config.is_bootstrap
  config.server_ip = normalizeServerIp(config.server_ip)

  // Исключения приложений: план сессии (full VPN). Bootstrap — без user exclusions.
  try {
    const { getExcludedExePathsForVpn, defaultStatePath } = require('./apps/exclusionsState')
    const { applyAppExclusionsForSession, clearActiveExcludedExePaths } = require('./apps/vpnAppExclusions')
    if (config.is_bootstrap) {
      clearActiveExcludedExePaths()
    } else {
      const paths = getExcludedExePathsForVpn(defaultStatePath(app.getPath('userData')))
      applyAppExclusionsForSession(paths, sendLog)
    }
  } catch (e) {
    sendLog(`[Apps] exclusions plan: ${e?.message || e}`)
  }

  const hashCount = (config.vk_hashes || []).filter(Boolean).length
  expectedCredGroups = Math.max(1, hashCount || 1)
  credGroupsResolved = 0
  wgFullTunnelUpgradeInFlight = false
  clearFullTunnelUpgradeTimer()
  // Main: один full install после GETCONF (без subnet→reinstall).
  // VK Auth идёт до WG — EACCES нет. Subnet-early + upgrade давали ~2× install.
  wgCredPhase = false
  const exePath = wdttExePath()
  if (!fs.existsSync(exePath)) {
    return { error: `wdtt-client.exe не найден: ${exePath}` }
  }
  const integrity = verifyWdttIntegrity({
    isPackaged: app.isPackaged,
    isDebugBuild,
    exePath,
    log: sendLog,
  })
  if (!integrity.ok) {
    sendLog(`[Integrity] ${integrity.reason}`)
    return { error: integrity.reason || 'Сборка повреждена' }
  }

  if (wdttProcess) {
    await stopWdttForReplace(sendLog, switching ? 'upgrade' : 'restart')
  }

  const tmpDir = app.getPath('temp')
  const confPath = path.join(tmpDir, 'wg-turn.conf')
  if (!switching && fs.existsSync(confPath)) fs.unlinkSync(confPath)

  const hashList = (config.vk_hashes || []).filter(Boolean)
  sessionVkHashes = hashList
  groupHashPrefix.clear()
  zeroWorkersSinceMs = 0
  const hashes = hashList.join(',')
  const rawN = Number(config.stream_count) || 63
  const captchaMode = String(config.captchaMode || config.captcha_mode || 'auto').trim() || 'auto'
  const vkAuthMode = String(config.vkAuthMode || config.vk_auth_mode || 'vkcalls').trim() || 'vkcalls'
  const workers = effectiveConnectWorkers({
    isBootstrap: !!config.is_bootstrap,
    vkAuthMode,
    streamCount: rawN,
  })
  sessionDnsOverride = String(config.dns_override || '').trim() || null
  if (sessionDnsOverride) {
    sendLog(`[WG] DNS override (debug): ${sessionDnsOverride}`)
  }
  // Legacy: boot 1 группа (капча), затем рамп до target — иначе YouTube без полосы @9.
  const legacyCaptcha = !config.is_bootstrap && vkAuthMode === 'legacy'
  sessionTargetWorkers = workers
  // Boot 9 (1 группа → быстрый GETCONF) → ramp до target.
  const bootWorkers = config.is_bootstrap
    ? workers
    : legacyCaptcha
      ? WORKERS_PER_GROUP
    // Boot = по группе на каждый хеш (волна), иначе single-flow сидит на 1 хеше до рампа.
    : Math.min(Math.max(9, hashList.length * 9), workers)
  if (legacyCaptcha && workers > WORKERS_PER_GROUP) {
    sendLog(`[VPN] legacy/captcha: boot ${WORKERS_PER_GROUP} → target ${workers} (рамп, без шторма)`)
  }
  const useRamp = !config.is_bootstrap && workers > bootWorkers
  sendLog(
    `[VPN] connect n=${bootWorkers}${useRamp ? `→${workers}` : ''}${config.is_bootstrap ? ' (bootstrap)' : ''} hashes=${hashList.length} vk=${vkAuthMode} captcha=${captchaMode}`,
  )
  const args = [
    '-peer', `${config.server_ip}:${config.server_port}`,
    '-vk', hashes,
    '-password', config.wdtt_password,
    '-device-id', String(config.device_id || ''),
    '-listen', '127.0.0.1:9000',
    '-n', String(bootWorkers),
    '-captcha-mode', captchaMode,
    '-vk-auth-mode', vkAuthMode,
  ]
  if (useRamp) {
    // Legacy: пауза между группами — каждая может снова пройти автокапчу.
    const rampFirst = legacyCaptcha ? '6s' : '3s'
    const rampNext = legacyCaptcha ? '5s' : '2s'
    args.push('-target-n', String(workers), '-ramp-first', rampFirst, '-ramp-next', rampNext)
  }

  // DNS bypass в фоне — не блокировать spawn/подписку на stdout (раньше теряли секунды).
  const excludePromise = collectExcludeIPs(config)
  const apiConf = buildWgConfigFromApi(config)

  const gen = ++wdttGeneration
  const proc = spawn(exePath, args, {
    cwd: tmpDir,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true, // иначе Go-консоль всплывает (особенно после OTA / runAfterFinish)
  })
  wdttProcess = proc
  wdttStartedAtMs = Date.now()
  if (!switching) {
    wgApplied = false
    tunnelReadySent = false
    activeWorkerCount = 0
  } else {
    activeWorkerCount = 0
  }

  let excludeIPs = [SERVER_IP_FALLBACK]
  const peerIp = normalizeServerIp(config?.server_ip)
  if (peerIp) excludeIPs.push(peerIp)
  sessionExcludeIPs = [...excludeIPs]

  let wgAttempted = false
  let wgFailed = false
  let wgPoll = null
  let wgTimers = []

  const clearWgRetries = () => {
    if (wgPoll) { clearInterval(wgPoll); wgPoll = null }
    wgTimers.forEach((t) => {
      if (t && typeof t.close === 'function') {
        try { t.close() } catch { /* fs.watch */ }
      } else {
        try { clearTimeout(t) } catch { /* ignore */ }
      }
    })
    wgTimers = []
  }

  const sendVpnError = (msg) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-error', msg)
    }
  }

  const failWireGuard = (msg) => {
    if (wgApplied || wgFailed) return
    wgFailed = true
    wgAttempted = true
    clearWgRetries()
    sendVpnError(msg)
  }

  let wgInstallInFlight = false

  const upgradeToFullTunnel = async (source = 'groups', attempt = 1) => {
    if (!wgCredPhase || wgFullTunnelUpgradeInFlight) return
    if (!wgApplied) {
      if (attempt <= 20) {
        setTimeout(() => { void upgradeToFullTunnel(source, attempt + 1) }, 500)
      }
      return
    }
    while (wgInstallInFlight) {
      await sleep(200)
    }
    wgFullTunnelUpgradeInFlight = true
    clearFullTunnelUpgradeTimer()
    sendLog(`[WG] Переключение на полный туннель (${source})…`)
    try {
      if (!vpnSessionActive) return
      if (!fs.existsSync(confPath)) {
        sendLog('[WG] full tunnel upgrade: нет wg-turn.conf', 'W')
        return
      }
      // skipForceStop:false — reinstall: syncconf на Windows НЕ меняет AllowedIPs
      const ok = await applyWireGuardConfig(confPath, isDev, __dirname, sendLog, [...excludeIPs], {
        skipWdttWait: true,
        subnetOnly: false,
        skipForceStop: false,
        reuseRuntime: true,
        dnsOverride: sessionDnsOverride,
      })
      if (!vpnSessionActive) {
        sendLog('[WG] full tunnel upgrade отменён (disconnect)')
        return
      }
      if (ok) {
        wgCredPhase = false
        sendLog(`[WG] Полный туннель активен, DNS = ${sessionDnsOverride || '1.1.1.1 + 77.88.8.8'}`)
        // После reinstall маршруты мигают → EACCES/ECONNABORTED на API.
        // Bypass сразу + ещё раз через 1с/3с, ConfigSync чуть позже.
        wgRouteSettleUntil = Date.now() + 10_000
        await addServerBypassRoutes([...excludeIPs], sendLog)
        await ensureNipIoBypassRoutes(sendLog)
        scheduleBypassRefresh(sendLog)
        try {
          const { refreshAppExclusionBypassAfterTunnel } = require('./apps/vpnAppExclusions')
          await refreshAppExclusionBypassAfterTunnel(sendLog)
          setTimeout(() => { void refreshAppExclusionBypassAfterTunnel(sendLog) }, 1500)
        } catch (e) {
          sendLog(`[Apps] bypass after full tunnel: ${e?.message || e}`)
        }
        setTimeout(() => { void addServerBypassRoutes([...excludeIPs], sendLog) }, 1000)
        setTimeout(() => { void addServerBypassRoutes([...excludeIPs], sendLog) }, 3000)
        setTimeout(() => { ensureVpnReadyEvent(sendLog) }, 1500)
      } else if (attempt < 3) {
        sendLog(`[WG] full tunnel retry ${attempt + 1}/3…`, 'W')
        wgFullTunnelUpgradeInFlight = false
        setTimeout(() => { void upgradeToFullTunnel(`${source}-retry`, attempt + 1) }, 3000)
        return
      } else {
        sendLog('[WG] full tunnel upgrade failed — YouTube может не работать', 'W')
      }
    } catch (e) {
      sendLog(`[WG] full tunnel upgrade: ${e?.message || e}`, 'W')
      if (attempt < 3) {
        wgFullTunnelUpgradeInFlight = false
        setTimeout(() => { void upgradeToFullTunnel(`${source}-retry`, attempt + 1) }, 3000)
        return
      }
    } finally {
      wgFullTunnelUpgradeInFlight = false
    }
  }

  const maybeScheduleFullTunnelUpgrade = () => {
    if (!wgCredPhase || fullTunnelUpgradeTimer) return
    fullTunnelUpgradeTimer = setTimeout(() => {
      fullTunnelUpgradeTimer = null
      if (activeWorkerCount >= fullTunnelTargetWorkers()) {
        void upgradeToFullTunnel('timeout-full-workers')
      }
    }, 8_000)
  }

  const onCredGroupResolved = (groupId) => {
    if (!wgCredPhase) return
    credGroupsResolved += 1
    const readyForFullWorkers = activeWorkerCount >= fullTunnelTargetWorkers()
    const minGroups = minCredGroupsForFullTunnel(expectedCredGroups)
    if ((credGroupsResolved >= minGroups || groupId >= minGroups) && readyForFullWorkers) {
      void upgradeToFullTunnel(`group #${groupId}`)
    }
  }

  const tryApplyWg = async (confText, source = 'file') => {
    if (switching && wgApplied) return false
    if (wgApplied || wgFailed || wgInstallInFlight || !confText) return false
    if (!confText.includes('[Interface]')) return false
    if (wgAttempted) return false

    let normalizedConf = confText
    // Telegram latency experiment: MTU 1200 (меньше фрагментации поверх VK DTLS).
    if (/^\s*MTU\s*=/m.test(normalizedConf)) {
      normalizedConf = normalizedConf.replace(/^\s*MTU\s*=.*/m, 'MTU = 1200')
    } else {
      normalizedConf = normalizedConf.replace(
        /(\[Interface\][^\[]*)/,
        (m) => m.trimEnd() + '\nMTU = 1200\n',
      )
    }
    sendLog('[WG] MTU = 1200 (Telegram latency experiment)')
    normalizedConf = normalizeWgConfText(normalizedConf)

    wgInstallInFlight = true

    sendLog(`[WG] Применение конфига (${source})...`)
    sendLog('[WG] Ожидание WDTT UDP 127.0.0.1:9000...')
    // confPath: GETCONF уже на диске (wdtt-file) — не ждать лишний UDP poll
    const proxyWaitMs = switching ? 4_000 : 6_000
    const wdttReady = await waitForWdttProxy('127.0.0.1', 9000, proxyWaitMs, sendLog, confPath)
    if (!wdttReady) {
      wgInstallInFlight = false
      wgAttempted = false
      failWireGuard('Таймаут: WDTT не подключился к серверу')
      return false
    }

    fs.writeFileSync(confPath, normalizedConf)

    // syncconf если служба уже есть (reconnect) — без uninstall
    const alreadyUp = await isServiceRunningAsync()
    const wgPromise = applyWireGuardConfig(confPath, isDev, __dirname, sendLog, [...excludeIPs], {
      skipWdttWait: true,
      subnetOnly: vpnBootstrapMode || wgCredPhase,
      skipForceStop: alreadyUp,
      reuseRuntime: true,
      dnsOverride: sessionDnsOverride,
    })
    const timeoutMs = isProcessElevated() ? 70000 : 90000
    let ok = false
    try {
      ok = await Promise.race([
        wgPromise,
        new Promise((_, reject) => setTimeout(() => reject(new Error('WG install timeout')), timeoutMs)),
      ])
    } catch (e) {
      sendLog('[WG] ' + (e.message || 'install failed'))
      ok = false
    } finally {
      wgInstallInFlight = false
    }
    if (!ok && (await isServiceRunningAsync())) {
      sendLog('[WG] Туннель/служба активны после таймаута — считаем успехом')
      ok = true
    }
    if (ok) {
      wgApplied = true
      wgAttempted = true
      clearWgRetries()
      await addServerBypassRoutes([...excludeIPs], sendLog)
      await ensureNipIoBypassRoutes(sendLog)
      scheduleBypassRefresh(sendLog)
      try {
        const { refreshAppExclusionBypassAfterTunnel } = require('./apps/vpnAppExclusions')
        await refreshAppExclusionBypassAfterTunnel(sendLog)
      } catch (e) {
        sendLog(`[Apps] bypass after tunnel: ${e?.message || e}`)
      }
      if (wgCredPhase) maybeScheduleFullTunnelUpgrade()
      scheduleTunnelReadyPoll(sendLog)
      ensureVpnReadyEvent(sendLog)
      return true
    }
    failWireGuard(
      isProcessElevated()
        ? 'WireGuard не запустился. Проверьте services.msc → WireGuardTunnel$wg-turn'
        : 'Разрешите UAC (Да) или запустите «Silent VPN (Admin).bat»',
    )
    return false
  }

  const applyFromFile = async () => {
    if (!fs.existsSync(confPath)) return false
    const text = fs.readFileSync(confPath, 'utf8')
    if (!text.includes('[Interface]')) return false
    if (wgApplied || wgInstallInFlight) return false
    if (wgFailed) {
      wgFailed = false
      wgAttempted = false
    }
    return tryApplyWg(text, 'wdtt-file')
  }

  let applyFromFileQueued = false
  const requestApplyFromFile = () => {
    if (applyFromFileQueued || wgApplied || wgInstallInFlight) return
    // Пока WebView капчи грузит id.vk.ru — не рвём сеть full-tunnel install.
    if (captchaInProgress) {
      pendingWgAfterCaptcha = true
      sendLog('[WG] ждём капчу перед установкой туннеля')
      return
    }
    applyFromFileQueued = true
    setImmediate(() => {
      applyFromFileQueued = false
      void applyFromFile()
    })
  }
  requestApplyWgAfterCaptcha = requestApplyFromFile

  const handleLine = (line) => {
    const lineTrim = String(line || '').trim()
    if (lineTrim.startsWith('CAPTCHA_SOLVE|')) {
      scheduleCaptchaSolve(lineTrim)
      return
    }
    maybeReportHashFailureFromLine(line)
    const statsMatch = line.match(/Активных:\s*(\d+)/)
    if (statsMatch) {
      activeWorkerCount = parseInt(statsMatch[1], 10)
      if (activeWorkerCount > 0) zeroWorkersSinceMs = 0
      if (
        wgCredPhase &&
        wgApplied &&
        activeWorkerCount >= fullTunnelTargetWorkers() &&
        !wgFullTunnelUpgradeInFlight
      ) {
        void upgradeToFullTunnel(`workers>=${fullTunnelTargetWorkers()}`)
      }
      if (wgApplied) ensureVpnReadyEvent(sendLog)
      const now = Date.now()
      if (now - lastStatsLogToUiAt >= 8000) {
        lastStatsLogToUiAt = now
        sendLog(line)
      }
      return
    }
    sendLog(line)
    const credOkMatch = line.match(/\[ГРУППА #(\d+)\] Креды OK/)
    if (credOkMatch) {
      onCredGroupResolved(parseInt(credOkMatch[1], 10))
    } else if (
      /Первые креды|Учётные данные проверены|Креды OK/i.test(line)
    ) {
      onCredGroupResolved(Math.min(credGroupsResolved + 1, expectedCredGroups))
    }
    const credFailMatch = line.match(/\[ГРУППА #(\d+)\] Ошибка кредов/)
    if (credFailMatch) {
      onCredGroupResolved(parseInt(credFailMatch[1], 10))
    }
    const regMatch = line.match(/зарегистрирован \(всего:\s*(\d+)\)/)
    if (regMatch) {
      activeWorkerCount = parseInt(regMatch[1], 10)
      if (!wgApplied && !wgInstallInFlight && activeWorkerCount >= 1) {
        requestApplyFromFile()
      }
      if (
        wgCredPhase &&
        wgApplied &&
        activeWorkerCount >= fullTunnelTargetWorkers() &&
        !wgFullTunnelUpgradeInFlight
      ) {
        void upgradeToFullTunnel(`workers>=${fullTunnelTargetWorkers()}`)
      }
      if (wgApplied) ensureVpnReadyEvent(sendLog)
    }
    // TURN IP в AllowedIPs не добавляем: split 0.0.0.0/0 → сотни маршрутов, WG на Windows падает (exit 10).

    if (!switching && line.includes('[КОНФИГ]') && line.includes('Сохранён')) {
      if (wgFailed) {
        wgFailed = false
        wgAttempted = false
      }
      requestApplyFromFile()
      return
    }

    if (line.includes('╔') && line.includes('WireGuard')) {
      return
    }
  }

  let collecting = false
  const boxBuilder = []
  const parseBox = async (line) => {
    if (!config.is_bootstrap) return
    if (line.includes('╔') && line.includes('WireGuard')) {
      collecting = true
      boxBuilder.length = 0
      return
    }
    if (!collecting) return
    if (line.includes('╚')) {
      collecting = false
      const cfg = boxBuilder.join('\n').trim()
      if (cfg && !(switching && wgApplied)) await tryApplyWg(cfg, 'box')
      return
    }
    if (line.includes('║')) {
      const c = line.replace(/║/g, '').trim()
      if (c) boxBuilder.push(c)
    }
  }

  proc.stdout.on('data', (d) => {
    if (gen !== wdttGeneration) return
    d.toString().split('\n').forEach(l => {
      if (!l) return
      handleLine(l)
      parseBox(l)
    })
  })
  proc.stderr.on('data', (d) => {
    if (gen !== wdttGeneration) return
    d.toString().split('\n').forEach(l => { if (l) handleLine(l) })
  })

  proc.on('close', (code) => {
    if (gen !== wdttGeneration || wdttReplacing) return
    clearWgRetries()
    if (wdttProcess === proc) wdttProcess = null
    activeWorkerCount = 0
    if (transportSwitching && vpnSessionActive && !isQuitting) {
      // Это плановое переключение транспорта — UI не трогаем и WG не опускаем.
      return
    }
    if (vpnSessionActive && wgApplied && !isQuitting && !transportSwitching) {
      sendLog(`[VPN] wdtt завершился (code=${code}), WG остаётся — перезапуск транспорта…`)
      transportSwitching = true
      scheduleWdttRelaunch(800)
      return
    }
    transportSwitching = false
    void stopWireGuardTunnel(isDev, __dirname, sendLog, sessionExcludeIPs)
    clearBypassRefresh()
    wgApplied = false
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-stopped', code)
    }
  })

  if (switching && wgApplied) {
    transportSwitching = false
    return { success: true }
  }

  // Poll GETCONF каждые 150мс + fs.watch — WG сразу после первого успешного auth
  wgPoll = setInterval(() => {
    if (wgApplied || wgFailed || wgInstallInFlight) {
      if (wgApplied || wgFailed) clearWgRetries()
      return
    }
    void applyFromFile()
  }, 150)

  try {
    const confWatcher = fs.watch(tmpDir, { persistent: false }, (_eventType, filename) => {
      if (!filename || String(filename).toLowerCase() !== 'wg-turn.conf') return
      if (wgApplied || wgFailed || wgInstallInFlight) return
      requestApplyFromFile()
    })
    wgTimers.push(confWatcher)
  } catch { /* watch недоступен — остаётся poll */ }

  void excludePromise.then((resolved) => {
    if (!resolved?.length) return
    excludeIPs = resolved
    sessionExcludeIPs = [...excludeIPs]
    sendLog(`[WG] Bypass hosts: ${excludeIPs.length} (API/peer + VK)`)
    if (wgApplied) void addServerBypassRoutes(excludeIPs, sendLog)
  }).catch(() => {})

  // НЕ api-early: чужие ключи + syncconf на Windows → мёртвый 10.66.66.1.
  // Main: только GETCONF (wdtt-file). Bootstrap: api-fallback через 5с.
  if (apiConf && config.is_bootstrap) {
    wgTimers.push(setTimeout(async () => {
      if (wgApplied || wgFailed || wgInstallInFlight) return
      await tryApplyWg(apiConf, 'api-fallback')
    }, 5_000))
  }

  return { success: true }
}

ipcMain.handle('vpn-connect', async (_, config) => {
  trace().enter('Main.vpnConnect', `bootstrap=${!!config?.is_bootstrap} n=${config?.stream_count ?? '?'}`)
  vkFloodEscalatePending = false
  const wantBootstrap = !!config?.is_bootstrap
  if (vpnConnectInFlight) {
    sendLog('[VPN] connect: уже выполняется, без перезапуска')
    ensureVpnReadyEvent(sendLog)
    return { success: true, skipped: true }
  }

  if (!wantBootstrap && vpnBootstrapMode) {
    sendLog('[VPN] connect: смена bootstrap → main, полный перезапуск')
    await cleanupVpnAsync()
  }

  if (vpnSessionActive && isTransportHealthy() && wantBootstrap === vpnBootstrapMode) {
    sendLog('[VPN] connect: туннель уже работает')
    ensureVpnReadyEvent(sendLog)
    return { success: true, alreadyActive: true }
  }

  vpnConnectInFlight = true
  try {
    // Не ждать полный uninstall: cap 1.5с; не убивать живую WG — syncconf на connect.
    await Promise.race([waitWgStopIdle(), sleep(1500)])
    if (wdttProcess && !transportSwitching && !isTransportHealthy()) {
      sendLog('[VPN] Переподключение: остановка предыдущей сессии...')
      await cleanupVpnAsync()
    }
    // Службу wg-turn НЕ снимаем заранее — apply сделает syncconf (~1с) вместо install.

    const exePath = wdttExePath()
    if (!fs.existsSync(exePath)) {
      return { error: `wdtt-client.exe не найден: ${exePath}` }
    }

    lastVpnConnectConfig = config
    vpnSessionActive = true
    connectStartedAtMs = Date.now()
    pausedForNetwork = false
    transportSwitching = false

    const result = await beginWdttSession(config, { switching: false })
    if (!result.error) {
      startNetworkMonitor()
      startZeroWorkersWatchdog()
    }
    trace().exit('Main.vpnConnect', result.error ? `error=${result.error}` : 'ok')
    return result
  } finally {
    vpnConnectInFlight = false
  }
})

ipcMain.handle('vpn-disconnect', async (_, opts) => {
  if (opts?.slow) {
    await cleanupVpnAsync()
    return { success: true }
  }
  await fastDisconnectVpn()
  return { success: true }
})

ipcMain.handle('vpn-read-config', async () => {
  const confPath = path.join(app.getPath('temp'), 'wg-turn.conf')
  return fs.existsSync(confPath) ? fs.readFileSync(confPath, 'utf8') : null
})

ipcMain.handle('vpn-is-ready', async () => ({
  ready: isVpnReadyForUi() && !vpnBootstrapMode,
  bootstrap: vpnBootstrapMode && isVpnReadyForUi(),
  workers: activeWorkerCount,
  target: sessionTargetWorkers,
  min: minWorkersForTunnelReady(vpnBootstrapMode),
}))

ipcMain.handle('vpn-consume-flood-escalate', async () => consumeVkFloodEscalate())

ipcMain.handle('app-version', () => app.getVersion())

const UPDATE_PUBLIC_BASE = 'https://132-243-234-162.nip.io'
const UPDATE_HOST = '132-243-234-162.nip.io'
const TUNNEL_API_ORIGIN = 'http://10.66.66.1:8000'

/** При полном VPN OTA только через tunnel — public IP hairpin через 0.0.0.0/0 не доходит. */
function shouldUseTunnelForOta() {
  return !!(wgApplied && vpnSessionActive && !vpnBootstrapMode)
}

function updateCheckQuery(platform, version) {
  return `/api/updates/check?platform=${encodeURIComponent(platform || 'pc')}&version=${encodeURIComponent(version || '')}`
}

/**
 * URL для скачивания OTA.
 * - VPN on → всегда /api/updates/download/pc (tunnel), НЕ pathname от GitHub
 * - VPN off → абсолютный GitHub/HTTPS как есть; relative → public nip.io
 * Баг 1.0.152: GitHub URL превращался в http://10.66.66.1:8000/silentvpn3/... → 404 HTML → «100% / повреждён».
 */
function resolveUpdateDownloadUrl(urlOrPath, tunnelPath) {
  if (shouldUseTunnelForOta()) {
    const tp = String(tunnelPath || '/api/updates/download/pc').trim() || '/api/updates/download/pc'
    const path = tp.startsWith('/') ? tp : `/${tp}`
    return `${TUNNEL_API_ORIGIN}${path}`
  }
  const raw = String(urlOrPath || '').trim()
  if (!raw) return null
  if (/^https?:\/\//i.test(raw)) {
    return raw
  }
  const pathname = raw.startsWith('/') ? raw : `/${raw}`
  return `${UPDATE_PUBLIC_BASE}${pathname}`
}

/** Минимальная проверка, что скачали NSIS/PE, а не HTML 404. */
function assertValidPcInstaller(destPath, expectedSize) {
  if (!destPath || !fs.existsSync(destPath)) {
    throw new Error('Файл обновления не найден')
  }
  const st = fs.statSync(destPath)
  const minBytes = 1_000_000
  if (st.size < minBytes) {
    try { fs.unlinkSync(destPath) } catch { /* ignore */ }
    throw new Error(`Файл повреждён или пустой (${st.size} байт) — скачивание не удалось`)
  }
  const expect = Number(expectedSize) || 0
  if (expect > minBytes && st.size < Math.floor(expect * 0.5)) {
    try { fs.unlinkSync(destPath) } catch { /* ignore */ }
    throw new Error(`Файл повреждён (ожидалось ~${expect} байт, получено ${st.size})`)
  }
  const fd = fs.openSync(destPath, 'r')
  try {
    const buf = Buffer.alloc(2)
    fs.readSync(fd, buf, 0, 2, 0)
    if (buf[0] !== 0x4d || buf[1] !== 0x5a) {
      try { fs.unlinkSync(destPath) } catch { /* ignore */ }
      throw new Error('Файл повреждён (это не установщик Windows)')
    }
  } finally {
    fs.closeSync(fd)
  }
}

/** PC: API через public HTTPS (IP сервера вне туннеля + bypass). */
function publicDirectRequest({ method = 'GET', path: reqPath, headers = {}, body = null, timeout = 20000 }) {
  return backendHttpRequest({
    protocol: 'https',
    hostname: SERVER_IP_FALLBACK,
    port: 443,
    path: reqPath,
    method,
    headers: { ...headers, Host: UPDATE_HOST },
    body,
    timeout,
    rejectUnauthorized: false,
    servername: UPDATE_HOST,
  })
}

function tunnelHttpRequest({ method = 'GET', path: reqPath, headers = {}, body = null, timeout = 8000 }) {
  return backendHttpRequest({
    protocol: 'http',
    hostname: '10.66.66.1',
    port: 8000,
    path: reqPath,
    method,
    headers: { ...headers, Host: '10.66.66.1' },
    body,
    timeout,
  })
}

/** Любой HTTP-статус (включая 4xx) → resolve; сеть/таймаут → reject. */
function backendHttpRequest({
  protocol,
  hostname,
  port,
  path: reqPath,
  method = 'GET',
  headers = {},
  body = null,
  timeout = 20000,
  rejectUnauthorized,
  servername,
}) {
  return new Promise((resolve, reject) => {
    const path = reqPath.startsWith('/') ? reqPath : `/${reqPath}`
    const hdrs = {}
    for (const [k, v] of Object.entries(headers || {})) {
      if (v == null) continue
      const key = String(k)
      // Не тащим чужой Content-Length — пересчитаем сами
      if (key.toLowerCase() === 'content-length') continue
      if (key.toLowerCase() === 'host') continue
      hdrs[key] = String(v)
    }
    for (const [k, v] of Object.entries(headers || {})) {
      if (k.toLowerCase() === 'host' && v != null) hdrs.Host = String(v)
    }

    let payload = null
    if (body != null && body !== '') {
      payload = typeof body === 'string' ? body : JSON.stringify(body)
      if (!Object.keys(hdrs).some((k) => k.toLowerCase() === 'content-type')) {
        hdrs['Content-Type'] = 'application/json'
      }
      hdrs['Content-Length'] = Buffer.byteLength(payload)
    }

    const opts = {
      hostname,
      port,
      path,
      method: String(method || 'GET').toUpperCase(),
      headers: hdrs,
      timeout,
    }
    if (protocol === 'https') {
      opts.rejectUnauthorized = rejectUnauthorized !== false ? false : true
      if (servername) opts.servername = servername
    }

    const proto = protocol === 'https' ? https : http
    const req = proto.request(opts, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        const loc = res.headers.location
        const nextPath = loc.startsWith('http') ? new URL(loc).pathname + new URL(loc).search : loc
        backendHttpRequest({
          protocol,
          hostname,
          port,
          path: nextPath,
          method,
          headers,
          body,
          timeout,
          rejectUnauthorized,
          servername,
        }).then(resolve).catch(reject)
        res.resume()
        return
      }
      let raw = ''
      res.on('data', (chunk) => { raw += chunk })
      res.on('end', () => {
        let data = raw
        try { data = JSON.parse(raw) } catch { /* plain text */ }
        // 4xx/5xx тоже resolve — иначе login 400 теряется и ломает fallback
        resolve({ status: res.statusCode || 0, data })
      })
    })
    req.on('error', reject)
    req.on('timeout', () => {
      req.destroy(new Error(protocol === 'https' ? 'API timeout' : 'Tunnel API timeout'))
    })
    if (payload != null) req.write(payload)
    req.end()
  })
}

ipcMain.handle('tunnel-api-request', async (_, payload) => {
  // Как Android: при поднятом WG API через 10.66.66.1; иначе / fallback — public HTTPS.
  // Важно: HTTP 4xx — не «сбой туннеля», а ответ API (вернуть в renderer).
  const p = payload || {}
  const opts = { ...p, timeout: p.timeout || 25_000 }
  const path = opts.path || ''

  // Во время капчи WG часто снят → public HTTPS ловит ECONNABORTED; ConfigSync/Update не долбим.
  if (captchaInProgress && !wgApplied) {
    const err = new Error('API paused during captcha')
    err.code = 'CAPTCHA_BUSY'
    throw err
  }
  // Сразу после капчи / WG settle — только tunnel, без шума public fallback.
  if (Date.now() < apiQuietUntil && wgApplied) {
    try {
      const res = await tunnelHttpRequest({
        ...opts,
        timeout: Math.min(opts.timeout || 8000, 6000),
      })
      if (res.status >= 200 && res.status < 500) return res
    } catch { /* fall through to normal path */ }
  }

  const viaPublic = async () => {
    // Full tunnel без bypass → hairpin на VPS public IP / nip.io зависает.
    await ensurePublicApiBypass(sendLog)
    return publicDirectRequest(opts)
  }

  if (wgApplied) {
    const settling = Date.now() < wgRouteSettleUntil
    const fragile = wgFullTunnelUpgradeInFlight || wgCredPhase || settling
    const maxAttempts = fragile ? 4 : 2
    let lastErr = null
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const res = await tunnelHttpRequest({
          ...opts,
          // Во время upgrade/settle маршруты мигают — короткий timeout + retry
          timeout: fragile ? Math.min(opts.timeout || 8000, 5000) : Math.min(opts.timeout || 8000, 8000),
        })
        if (res.status >= 200 && res.status < 500) {
          if (res.status >= 400) {
            sendLog(`[API] tunnel ${path} → HTTP ${res.status}`)
          }
          return res
        }
        // 5xx — попробовать public
        sendLog(`[API] tunnel ${path} HTTP ${res.status} → HTTPS ${SERVER_IP_FALLBACK}`)
        return await viaPublic()
      } catch (e) {
        lastErr = e
        const msg = String(e?.message || e)
        // EACCES/ECONNABORTED — типично при WG reinstall (маршруты/адаптер мигают)
        const transient = /ECONNRESET|ECONNREFUSED|ECONNABORTED|EACCES|ETIMEDOUT|timeout|Tunnel API/i.test(msg)
        if (transient && attempt < maxAttempts) {
          // Восстановить bypass к API IP — иначе public fallback тоже мёртв
          await ensurePublicApiBypass(sendLog)
          await sleep(500 * attempt)
          continue
        }
        if (!(fragile && transient)) {
          sendLog(`[API] tunnel 10.66.66.1 fail: ${msg} → HTTPS ${SERVER_IP_FALLBACK}`)
        } else {
          sendLog(`[API] tunnel briefly unavailable during full-tunnel upgrade → HTTPS`)
        }
        try {
          return await viaPublic()
        } catch (pubErr) {
          const pubMsg = String(pubErr?.message || pubErr)
          if (/EACCES|ECONNABORTED|ECONNRESET|ETIMEDOUT/i.test(pubMsg) && attempt < maxAttempts) {
            await ensurePublicApiBypass(sendLog)
            await sleep(600 * attempt)
            continue
          }
          throw pubErr
        }
      }
    }
    sendLog(`[API] tunnel 10.66.66.1 fail: ${lastErr?.message || lastErr} → HTTPS ${SERVER_IP_FALLBACK}`)
    return viaPublic()
  }
  return publicDirectRequest(opts)
})

function fetchJsonGet(url, hostHeader = null) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url)
    const isHttps = urlObj.protocol === 'https:'
    const proto = isHttps ? https : http
    const opts = isHttps
      ? {
          hostname: urlObj.hostname,
          port: urlObj.port || 443,
          path: urlObj.pathname + urlObj.search,
          rejectUnauthorized: false,
          servername: hostHeader || urlObj.hostname,
          headers: hostHeader ? { Host: hostHeader } : undefined,
        }
      : { hostname: urlObj.hostname, port: urlObj.port || 80, path: urlObj.pathname + urlObj.search }
    const req = proto.get(opts, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        fetchJsonGet(res.headers.location, hostHeader).then(resolve).catch(reject)
        res.resume()
        return
      }
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode}`))
        res.resume()
        return
      }
      let body = ''
      res.on('data', (chunk) => { body += chunk })
      res.on('end', () => {
        try {
          resolve(JSON.parse(body))
        } catch (e) {
          reject(e)
        }
      })
    })
    req.on('error', reject)
    req.setTimeout(45_000, () => {
      req.destroy(new Error('Update check timeout'))
    })
  })
}

ipcMain.handle('app-update-check', async (_, { version, platform = 'pc' }) => {
  const q = updateCheckQuery(platform, version)
  if (captchaInProgress && !wgApplied) {
    return null
  }
  if (shouldUseTunnelForOta() || wgApplied) {
    try {
      const res = await tunnelHttpRequest({ method: 'GET', path: q, timeout: 15_000 })
      if (res.status === 200 && res.data) {
        sendLog('[Update] check via tunnel 10.66.66.1 OK')
        return res.data
      }
      sendLog(`[Update] tunnel check HTTP ${res.status} → public`)
    } catch (e) {
      sendLog(`[Update] tunnel check fail: ${e?.message || e} → public`)
    }
  }
  try {
    await ensurePublicApiBypass(sendLog)
    return await fetchJsonGet(`${UPDATE_PUBLIC_BASE}${q}`)
  } catch (e) {
    try {
      await ensurePublicApiBypass(sendLog)
      return await fetchJsonGet(`https://${SERVER_IP_FALLBACK}${q}`, UPDATE_HOST)
    } catch (e2) {
      sendLog(`[Update] check fail: ${e2?.message || e2}`)
      return null
    }
  }
})

function downloadFileWithProgress(url, destPath, onProgress) {
  return new Promise((resolve, reject) => {
    let urlObj
    try {
      urlObj = new URL(url)
    } catch (e) {
      reject(e)
      return
    }
    const isHttps = urlObj.protocol === 'https:'
    const proto = isHttps ? https : http
    const opts = {
      hostname: urlObj.hostname,
      port: urlObj.port || (isHttps ? 443 : 80),
      path: urlObj.pathname + urlObj.search,
      timeout: 600_000,
    }
    if (isHttps) {
      opts.rejectUnauthorized = false
      if (urlObj.hostname === SERVER_IP_FALLBACK) opts.servername = UPDATE_HOST
    }
    const req = proto.get(opts, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        const loc = res.headers.location
        const next = loc.startsWith('http') ? loc : `${urlObj.protocol}//${urlObj.host}${loc}`
        downloadFileWithProgress(next, destPath, onProgress).then(resolve).catch(reject)
        res.resume()
        return
      }
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode}`))
        res.resume()
        return
      }
      const total = parseInt(res.headers['content-length'] || '0', 10)
      let received = 0
      const file = fs.createWriteStream(destPath)
      res.on('data', (chunk) => {
        received += chunk.length
        if (onProgress) {
          if (total > 0) onProgress(Math.min(99, Math.round((received / total) * 100)))
          else onProgress(Math.min(95, Math.round(received / (1024 * 1024)))) // без CL: грубо по МБ
        }
      })
      res.pipe(file)
      file.on('finish', () => file.close(() => resolve(destPath)))
      file.on('error', (err) => {
        fs.unlink(destPath, () => {})
        reject(err)
      })
    })
    req.on('error', reject)
    req.on('timeout', () => {
      req.destroy(new Error('Download timeout'))
    })
  })
}

ipcMain.handle('app-update-download', async (_, { url, filename, tunnelUrl, expectedSize }) => {
  try {
    const safeName = path.basename(filename || 'update.exe')
    const dest = path.join(app.getPath('temp'), safeName)
    const finalUrl = resolveUpdateDownloadUrl(url, tunnelUrl)
    if (!finalUrl) {
      return { ok: false, error: 'Empty download URL' }
    }
    sendLog(`[Update] download via ${finalUrl.startsWith(TUNNEL_API_ORIGIN) ? 'tunnel' : 'public'}: ${finalUrl}`)
    const sendProgress = (pct) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('update-progress', pct)
      }
    }
    await downloadFileWithProgress(finalUrl, dest, sendProgress)
    assertValidPcInstaller(dest, expectedSize)
    sendProgress(100)
    return { ok: true, path: dest }
  } catch (e) {
    return { ok: false, error: e?.message || String(e) }
  }
})

/**
 * OTA: отложенный запуск Setup ПОСЛЕ выхода Electron.
 *
 * Почему не spawn/Start-Process сразу:
 * 1) Job Object Electron убивает детей при app.exit
 * 2) Клиент requireAdministrator → Setup стартует без UAC-паузы
 * 3) NSIS customInit делает taskkill /IM "Silent VPN.exe" /T → если Setup ещё
 *    child клиента, /T убивает и сам установщик (100% → тишина)
 *
 * Bat: sleep → start Setup → когда Silent VPN.exe уже мёртв, /T безобиден.
 */
function schedulePcInstallerAfterExit(filePath) {
  const abs = path.resolve(filePath)
  if (!fs.existsSync(abs)) {
    return { ok: false, error: 'File not found' }
  }
  const logPath = path.join(app.getPath('temp'), 'silent-ota-launch.log')
  const batPath = path.join(app.getPath('temp'), `silent-ota-launch-${Date.now()}.cmd`)
  const setup = abs.replace(/"/g, '')
  const logEsc = logPath.replace(/"/g, '')
  const bat = [
    '@echo off',
    `echo [%date% %time%] waiting > "${logEsc}"`,
    'ping -n 4 127.0.0.1 >nul',
    `echo [%date% %time%] starting >> "${logEsc}"`,
    `start "" "${setup}"`,
    `echo [%date% %time%] start done >> "${logEsc}"`,
    'ping -n 2 127.0.0.1 >nul',
    'del "%~f0" >nul 2>&1',
    '',
  ].join('\r\n')
  fs.writeFileSync(batPath, bat, 'utf8')
  sendLog(`[Update] scheduled launcher: ${batPath}`)
  try {
    fs.writeFileSync(logPath, `[${new Date().toISOString()}] bat=${batPath}\nsetup=${setup}\n`, 'utf8')
  } catch { /* ignore */ }

  // cmd /c start запускает bat в новом окне вне job; сам cmd сразу выходит
  const child = spawn(
    process.env.ComSpec || 'cmd.exe',
    ['/d', '/c', 'start', '', '/min', batPath],
    {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      windowsVerbatimArguments: true,
    },
  )
  child.once('error', (e) => {
    sendLog(`[Update] schedule launcher error: ${e?.message || e}`)
  })
  child.unref()
  return { ok: true, batPath, logPath }
}

ipcMain.handle('app-update-install', async (_, filePath) => {
  try {
    if (!filePath || !fs.existsSync(filePath)) {
      return { ok: false, error: 'File not found' }
    }
    sendLog('[Update] stopping VPN before install…')
    try {
      networkMonitor?.stop()
      await fastDisconnectVpn()
    } catch { /* ignore */ }
    const { execSync } = require('child_process')
    for (const proc of ['wdtt-client.exe', 'wireguard.exe', 'wg.exe']) {
      try { execSync(`taskkill /F /IM ${proc}`, { stdio: 'ignore' }) } catch { /* ignore */ }
    }
    await sleep(300)

    sendLog('[Update] schedule installer after exit: ' + filePath)
    const scheduled = schedulePcInstallerAfterExit(filePath)
    if (!scheduled.ok) {
      return { ok: false, error: scheduled.error || 'schedule failed' }
    }

    isQuitting = true
    // Сразу выходим — bat подождёт ~3с и запустит Setup уже без нашего дерева процессов
    setImmediate(() => {
      try { app.exit(0) } catch { app.quit() }
    })
    return { ok: true }
  } catch (e) {
    return { ok: false, error: e?.message || String(e) }
  }
})

app.whenReady().then(async () => {
  if (process.defaultApp) {
    if (process.argv.length >= 2) {
      app.setAsDefaultProtocolClient('silentvpn', process.execPath, [path.resolve(process.argv[1])])
    }
  } else {
    app.setAsDefaultProtocolClient('silentvpn')
  }
  softTamperHints({ isPackaged: app.isPackaged, isDebugBuild, log: sendLog })

  // После OTA/установки: убиваем осиротевший wdtt и даём WireGuard дописаться.
  try {
    const { execSync } = require('child_process')
    execSync('taskkill /F /IM wdtt-client.exe', { stdio: 'ignore', windowsHide: true })
  } catch { /* нет процесса */ }

  const postInstallStamp = path.join('C:\\ProgramData\\SilentVPN', 'post-install.stamp')
  if (fs.existsSync(postInstallStamp)) {
    try { fs.unlinkSync(postInstallStamp) } catch { /* ignore */ }
    sendLog('[WG] Первый запуск после установки — ждём готовности WireGuard…')
    await sleep(2500)
    try {
      prepareRuntimeDir(isDev, __dirname, sendLog)
    } catch (e) {
      sendLog(`[WG] post-install warm: ${e?.message || e}`)
    }
  }

  createWindow()
  createTray()
  warmVkExcludeIps()
})

app.on('before-quit', () => {
  isQuitting = true
  cleanupVpn()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
