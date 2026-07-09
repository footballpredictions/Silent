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
} = require('./vpn/wireguard')
const { solveVkCaptcha, cancelCaptchaSolve } = require('./vk/captchaWebView')
const { resolveVkExcludeIps, warmVkExcludeIps } = require('./vpn/vkNetworkExcludes')
const buildFlags = require('./buildFlags')

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
let sessionTargetWorkers = 108
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
    show: true,
  })

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
    const isError = /error|ошиб|fail|timeout|FATAL/i.test(trimmed)
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

const WORKERS_PER_GROUP = 9
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
  sendLog(`[КАПЧА] ${mode === 'manual' ? 'ручное окно' : 'авто'} (${redirectUri.slice(0, 40)}…)`)

  let token = ''
  try {
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

ipcMain.handle('list-installed-apps', () => {
  const { listInstalledApps } = require('./apps/listInstalledApps')
  return listInstalledApps()
})

ipcMain.handle('window-minimize', () => mainWindow?.minimize())
ipcMain.handle('window-close', () => mainWindow?.hide())
ipcMain.handle('app-quit', () => {
  quitAppFully()
  return true
})
async function ensureNipIoBypassRoutes(sendLogFn = sendLog) {
  if (!wgApplied || vpnBootstrapMode || sessionExcludeIPs.length === 0) return
  await capturePhysicalGateway(sendLogFn)
  await addServerBypassRoutes(sessionExcludeIPs, sendLogFn)
  await sleep(500)
}

ipcMain.handle('open-external', async (_, url) => {
  if (typeof url === 'string' && /132-243-234-162\.nip\.io|132\.243\.234\.162/.test(url)) {
    await ensureNipIoBypassRoutes()
  }
  await shell.openExternal(url)
  return true
})
ipcMain.handle('get-admin-panel-url', () => 'https://132-243-234-162.nip.io/admin')
ipcMain.handle('open-admin-panel', async () => {
  const url = 'https://132-243-234-162.nip.io/admin'
  if (wgApplied && isWdttAlive() && !vpnBootstrapMode) {
    sendLog('[Admin] VPN on — bypass nip.io API IP, open ' + url)
    await ensureNipIoBypassRoutes()
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
  const rawN = Number(config.stream_count) || 108
  const workers = config.is_bootstrap
    ? Math.min(Math.max(rawN, 3), 108)
    : Math.min(Math.max(rawN, 9), 108)
  sessionTargetWorkers = workers
  const captchaMode = String(config.captchaMode || config.captcha_mode || 'auto').trim() || 'auto'
  const vkAuthMode = String(config.vkAuthMode || config.vk_auth_mode || 'vkcalls').trim() || 'vkcalls'
  // Boot 9 (1 группа → быстрый GETCONF) → ramp до target.
  const bootWorkers = config.is_bootstrap
    ? workers
    : Math.min(9, workers)
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
    args.push('-target-n', String(workers), '-ramp-first', '3s', '-ramp-next', '2s')
  }

  // DNS bypass в фоне — не блокировать spawn/подписку на stdout (раньше теряли секунды).
  const excludePromise = collectExcludeIPs(config)
  const apiConf = buildWgConfigFromApi(config)

  const gen = ++wdttGeneration
  const proc = spawn(exePath, args, { cwd: tmpDir, stdio: ['pipe', 'pipe', 'pipe'] })
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
      })
      if (!vpnSessionActive) {
        sendLog('[WG] full tunnel upgrade отменён (disconnect)')
        return
      }
      if (ok) {
        wgCredPhase = false
        sendLog('[WG] Полный туннель активен, DNS = 1.1.1.1 + 77.88.8.8')
        // После reinstall маршруты мигают → EACCES/ECONNABORTED на API.
        // Bypass сразу + ещё раз через 1с/3с, ConfigSync чуть позже.
        wgRouteSettleUntil = Date.now() + 10_000
        await addServerBypassRoutes([...excludeIPs], sendLog)
        scheduleBypassRefresh(sendLog)
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
    if (!normalizedConf.includes('MTU =')) {
      normalizedConf = normalizedConf.replace(
        /(\[Interface\][^\[]*)/,
        (m) => (m.includes('MTU =') ? m : m.trimEnd() + '\nMTU = 1280\n'),
      )
    }
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
      scheduleBypassRefresh(sendLog)
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
    applyFromFileQueued = true
    setImmediate(() => {
      applyFromFileQueued = false
      void applyFromFile()
    })
  }

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

ipcMain.handle('app-version', () => app.getVersion())

const UPDATE_PUBLIC_BASE = 'https://132-243-234-162.nip.io'
const UPDATE_HOST = '132-243-234-162.nip.io'

function updateCheckBaseUrl() {
  if (vpnSessionActive && wgApplied && !vpnBootstrapMode) {
    return `https://${SERVER_IP_FALLBACK}`
  }
  return UPDATE_PUBLIC_BASE
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
  if (wgApplied) {
    const settling = Date.now() < wgRouteSettleUntil
    const fragile = wgFullTunnelUpgradeInFlight || wgCredPhase || settling
    const maxAttempts = fragile ? 4 : 1
    let lastErr = null
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const res = await tunnelHttpRequest({
          ...opts,
          // Во время upgrade/settle маршруты мигают — короткий timeout + retry
          timeout: fragile ? Math.min(opts.timeout || 8000, 5000) : opts.timeout,
        })
        if (res.status >= 200 && res.status < 500) {
          if (res.status >= 400) {
            sendLog(`[API] tunnel ${path} → HTTP ${res.status}`)
          }
          return res
        }
        // 5xx — попробовать public
        sendLog(`[API] tunnel ${path} HTTP ${res.status} → HTTPS ${SERVER_IP_FALLBACK}`)
        return await publicDirectRequest(opts)
      } catch (e) {
        lastErr = e
        const msg = String(e?.message || e)
        // EACCES/ECONNABORTED — типично при WG reinstall (маршруты/адаптер мигают)
        const transient = /ECONNRESET|ECONNREFUSED|ECONNABORTED|EACCES|ETIMEDOUT|timeout|Tunnel API/i.test(msg)
        if (transient && attempt < maxAttempts) {
          await sleep(500 * attempt)
          continue
        }
        if (!(fragile && transient)) {
          sendLog(`[API] tunnel 10.66.66.1 fail: ${msg} → HTTPS ${SERVER_IP_FALLBACK}`)
        } else {
          sendLog(`[API] tunnel briefly unavailable during full-tunnel upgrade → HTTPS`)
        }
        try {
          return await publicDirectRequest(opts)
        } catch (pubErr) {
          const pubMsg = String(pubErr?.message || pubErr)
          if (/EACCES|ECONNABORTED|ECONNRESET|ETIMEDOUT/i.test(pubMsg) && attempt < maxAttempts) {
            await sleep(600 * attempt)
            continue
          }
          throw pubErr
        }
      }
    }
    sendLog(`[API] tunnel 10.66.66.1 fail: ${lastErr?.message || lastErr} → HTTPS ${SERVER_IP_FALLBACK}`)
    return publicDirectRequest(opts)
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
  const base = updateCheckBaseUrl()
  const hostHeader = base.includes(SERVER_IP_FALLBACK) ? UPDATE_HOST : null
  const url = `${base}/api/updates/check?platform=${encodeURIComponent(platform)}&version=${encodeURIComponent(version || '')}`
  try {
    return await fetchJsonGet(url, hostHeader)
  } catch (e) {
    sendLog(`[Update] check fail: ${e?.message || e}`)
    return null
  }
})

function downloadFileWithProgress(url, destPath, onProgress) {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http
    const opts = url.startsWith('https') ? { rejectUnauthorized: false } : {}
    const req = proto.get(url, opts, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        downloadFileWithProgress(res.headers.location, destPath, onProgress).then(resolve).catch(reject)
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
        if (total > 0 && onProgress) onProgress(Math.min(100, Math.round((received / total) * 100)))
      })
      res.pipe(file)
      file.on('finish', () => file.close(() => resolve(destPath)))
      file.on('error', (err) => {
        fs.unlink(destPath, () => {})
        reject(err)
      })
    })
    req.on('error', reject)
    req.setTimeout(600_000, () => {
      req.destroy(new Error('Download timeout'))
    })
  })
}

ipcMain.handle('app-update-download', async (_, { url, filename }) => {
  try {
    const safeName = path.basename(filename || 'update.exe')
    const dest = path.join(app.getPath('temp'), safeName)
    const sendProgress = (pct) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('update-progress', pct)
      }
    }
    await downloadFileWithProgress(url, dest, sendProgress)
    return { ok: true, path: dest }
  } catch (e) {
    return { ok: false, error: e?.message || String(e) }
  }
})

ipcMain.handle('app-update-install', async (_, filePath) => {
  try {
    if (!filePath || !fs.existsSync(filePath)) {
      return { ok: false, error: 'File not found' }
    }
    isQuitting = true
    sendLog('[Update] stopping VPN before install…')
    try {
      networkMonitor?.stop()
      await fastDisconnectVpn()
    } catch { /* ignore */ }
    const { execSync } = require('child_process')
    for (const proc of ['wdtt-client.exe', 'wireguard.exe', 'wg.exe']) {
      try { execSync(`taskkill /F /IM ${proc} /T`, { stdio: 'ignore' }) } catch { /* ignore */ }
    }
    await sleep(800)

    sendLog('[Update] launching installer: ' + filePath)
    const openErr = await shell.openPath(filePath)
    if (openErr) {
      return { ok: false, error: openErr }
    }
    setTimeout(() => app.quit(), 1500)
    return { ok: true }
  } catch (e) {
    return { ok: false, error: e?.message || String(e) }
  }
})

app.whenReady().then(() => {
  if (process.defaultApp) {
    if (process.argv.length >= 2) {
      app.setAsDefaultProtocolClient('silentvpn', process.execPath, [path.resolve(process.argv[1])])
    }
  } else {
    app.setAsDefaultProtocolClient('silentvpn')
  }
  createWindow()
  createTray()
  warmVkExcludeIps()
  // Предыдущее фоновое forceStop на старте убрано: оно могло сбивать подключение при раннем клике.
})

app.on('before-quit', () => {
  isQuitting = true
  cleanupVpn()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
