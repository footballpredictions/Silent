const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, clipboard } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')
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
  buildWgConfigFromApi,
  applyWireGuardConfig,
} = require('./vpn/wireguard')

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

const isDev = process.env.NODE_ENV === 'development'
const WIN_WIDTH = 265
const WIN_HEIGHT = 606

let mainWindow = null
let tray = null
let isQuitting = false
let wdttProcess = null
let wgApplied = false
let pendingVkDeepLink = null
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
let wdttGeneration = 0
let wdttReplacing = false

const SERVER_IP_FALLBACK = '132.243.234.162'

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
    show: false,
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
  })
  mainWindow.once('ready-to-show', () => mainWindow.show())
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
    { label: 'Выход', click: () => { isQuitting = true; cleanupVpn(); app.quit() } },
  ])
  tray.setContextMenu(contextMenu)
  tray.on('click', () => {
    if (mainWindow.isVisible()) mainWindow.hide()
    else { mainWindow.show(); mainWindow.focus() }
  })
}

function sendDebugLog(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('debug-log', payload)
  }
}

function sendWdttLog(entry) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('wdtt-log', entry)
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

  if (/^\[WG\]|^\[VPN\]|^\[Update\]/.test(trimmed)) {
    const isError = /error|ошиб|fail|таймаут/i.test(trimmed)
    const tag = trimmed.startsWith('[WG]') ? 'WireGuard' : 'VPN'
    sendWdttLog({
      key: `sys_${tag}_${trimmed.slice(0, 36).replace(/\d+/g, '#')}`,
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

function cleanupVpn() {
  resetHashFailureSessionState()
  vpnBootstrapMode = false
  wgCredPhase = false
  expectedCredGroups = 1
  credGroupsResolved = 0
  wgFullTunnelUpgradeInFlight = false
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
  if (wdttProcess) {
    try { wdttProcess.kill() } catch {}
    wdttProcess = null
  }
  stopWireGuardTunnel(isDev, __dirname, sendLog)
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

/** PC: «готов» = WG поднят + ≥1 воркер (моментально). Остальные — фоном. */
function minWorkersForTunnelReady(isBootstrap = false) {
  if (isBootstrap || vpnBootstrapMode) return 1
  return 1
}

function isVpnReadyForUi() {
  if (tunnelReadySent) return true
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
    mainWindow.webContents.send('vpn-ready', true)
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
  cleanupVpn()
  forceStopWireGuard(isDev, __dirname, sendLog)
  await waitForTunnelDown(2000, sendLog)
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
ipcMain.handle('open-external', (_, url) => shell.openExternal(url))
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
  // Пока группы 2–4 запрашивают VK-креды через LAN — только 10.66.66.0/24, не 0.0.0.0/0.
  wgCredPhase = !vpnBootstrapMode && expectedCredGroups > 1
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
  const workers = Math.min(Math.max(Number(config.stream_count) || 108, 9), 108)
  sessionTargetWorkers = workers
  sendLog(
    `[VPN] connect n=${workers} (одна сессия, как Android) hashes=${(config.vk_hashes || []).filter(Boolean).length}`,
  )
  const args = [
    '-peer', `${config.server_ip}:${config.server_port}`,
    '-vk', hashes,
    '-password', config.wdtt_password,
    '-device-id', String(config.device_id || ''),
    '-listen', '127.0.0.1:9000',
    '-n', String(workers),
    '-captcha-mode', 'auto',
  ]

  const gen = ++wdttGeneration
  const proc = spawn(exePath, args, { cwd: tmpDir })
  wdttProcess = proc
  wdttStartedAtMs = Date.now()
  if (!switching) {
    wgApplied = false
    tunnelReadySent = false
    activeWorkerCount = 0
  } else {
    activeWorkerCount = 0
  }

  const excludeIPs = new Set()
  if (config.server_ip) excludeIPs.add(config.server_ip)
  const apiConf = buildWgConfigFromApi(config)

  let wgAttempted = false
  let wgFailed = false
  let wgPoll = null
  let wgTimers = []

  const clearWgRetries = () => {
    if (wgPoll) { clearInterval(wgPoll); wgPoll = null }
    wgTimers.forEach(t => clearTimeout(t))
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
      if (!fs.existsSync(confPath)) {
        sendLog('[WG] full tunnel upgrade: нет wg-turn.conf', 'W')
        return
      }
      const ok = await applyWireGuardConfig(confPath, isDev, __dirname, sendLog, [...excludeIPs], {
        skipWdttWait: true,
        subnetOnly: false,
        skipForceStop: false,
        reuseRuntime: true,
      })
      if (ok) {
        wgCredPhase = false
        sendLog('[WG] Полный туннель активен, DNS = 1.1.1.1 + 77.88.8.8')
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
      void upgradeToFullTunnel('timeout')
    }, 25_000)
  }

  const onCredGroupResolved = (groupId) => {
    if (!wgCredPhase) return
    credGroupsResolved += 1
    if (credGroupsResolved >= expectedCredGroups || groupId >= expectedCredGroups) {
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

    wgInstallInFlight = true

    sendLog(`[WG] Применение конфига (${source})...`)
    sendLog('[WG] Ожидание WDTT UDP 127.0.0.1:9000...')
    const proxyWaitMs = switching ? 8_000 : 12_000
    const wdttReady = await waitForWdttProxy('127.0.0.1', 9000, proxyWaitMs, sendLog, confPath)
    if (!wdttReady) {
      wgInstallInFlight = false
      wgAttempted = false
      failWireGuard('Таймаут: WDTT не подключился к серверу')
      return false
    }

    fs.writeFileSync(confPath, normalizedConf)
    await sleep(150)

    const wgPromise = applyWireGuardConfig(confPath, isDev, __dirname, sendLog, [...excludeIPs], {
      skipWdttWait: true,
      subnetOnly: vpnBootstrapMode || wgCredPhase,
      skipForceStop: switching && (isTunnelUp() || isServiceRunning()),
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
    if (!ok && (isTunnelUp() || isServiceRunning())) {
      sendLog('[WG] Туннель/служба активны после таймаута — считаем успехом')
      ok = true
    }
    if (ok) {
      wgApplied = true
      wgAttempted = true
      clearWgRetries()
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

  const handleLine = async (line) => {
    maybeReportHashFailureFromLine(line)
    const statsMatch = line.match(/Активных:\s*(\d+)/)
    if (statsMatch) {
      activeWorkerCount = parseInt(statsMatch[1], 10)
      if (activeWorkerCount > 0) zeroWorkersSinceMs = 0
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
    }
    const credFailMatch = line.match(/\[ГРУППА #(\d+)\] Ошибка кредов/)
    if (credFailMatch) {
      onCredGroupResolved(parseInt(credFailMatch[1], 10))
    }
    const regMatch = line.match(/зарегистрирован \(всего:\s*(\d+)\)/)
    if (regMatch) {
      activeWorkerCount = parseInt(regMatch[1], 10)
      if (!wgApplied && !wgInstallInFlight && activeWorkerCount >= 1) {
        await applyFromFile()
      }
      if (wgApplied) ensureVpnReadyEvent(sendLog)
    }
    // TURN IP в AllowedIPs не добавляем: split 0.0.0.0/0 → сотни маршрутов, WG на Windows падает (exit 10).

    if (!switching && line.includes('[КОНФИГ]') && line.includes('Сохранён')) {
      if (wgFailed) {
        wgFailed = false
        wgAttempted = false
      }
      await applyFromFile()
      return
    }

    if (line.includes('╔') && line.includes('WireGuard')) {
      return
    }
  }

  let collecting = false
  const boxBuilder = []
  const parseBox = async (line) => {
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
    if (vpnSessionActive && wgApplied && !isQuitting && !transportSwitching) {
      sendLog(`[VPN] wdtt завершился (code=${code}), WG остаётся — перезапуск транспорта…`)
      transportSwitching = true
      scheduleWdttRelaunch(800)
      return
    }
    transportSwitching = false
    stopWireGuardTunnel(isDev, __dirname, sendLog)
    wgApplied = false
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-stopped', code)
    }
  })

  if (switching && wgApplied) {
    transportSwitching = false
    return { success: true }
  }

  wgPoll = setInterval(() => {
    if (wgApplied || wgFailed || wgInstallInFlight) {
      if (wgApplied || wgFailed) clearWgRetries()
      return
    }
    applyFromFile()
  }, 500)

  // Bootstrap: запасной конфиг с API. Основной VPN — только wg-turn.conf / box (GETCONF).
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
  if (vpnConnectInFlight) {
    sendLog('[VPN] connect: уже выполняется, без перезапуска')
    ensureVpnReadyEvent(sendLog)
    return { success: true, skipped: true }
  }

  if (vpnSessionActive && isTransportHealthy()) {
    sendLog('[VPN] connect: туннель уже работает')
    ensureVpnReadyEvent(sendLog)
    return { success: true, alreadyActive: true }
  }

  vpnConnectInFlight = true
  try {
    if (wdttProcess && !transportSwitching && !isTransportHealthy()) {
      sendLog('[VPN] Переподключение: остановка предыдущей сессии...')
      await cleanupVpnAsync()
    } else if (!wdttProcess && !wgApplied) {
      forceStopWireGuard(isDev, __dirname, sendLog)
      await waitForTunnelDown(8000, sendLog)
      await sleep(400)
    }

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
  ready: isVpnReadyForUi(),
  workers: activeWorkerCount,
  target: sessionTargetWorkers,
  min: minWorkersForTunnelReady(vpnBootstrapMode),
}))

ipcMain.handle('app-version', () => app.getVersion())

const UPDATE_PUBLIC_BASE = 'https://132-243-234-162.nip.io'

function fetchJsonGet(url) {
  return new Promise((resolve, reject) => {
    const proto = url.startsWith('https') ? https : http
    const opts = url.startsWith('https') ? { rejectUnauthorized: false } : {}
    const req = proto.get(url, opts, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        fetchJsonGet(res.headers.location).then(resolve).catch(reject)
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
  const url = `${UPDATE_PUBLIC_BASE}/api/updates/check?platform=${encodeURIComponent(platform)}&version=${encodeURIComponent(version || '')}`
  try {
    return await fetchJsonGet(url)
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
  // Сироты wireguard.exe после краша / прошлых версий — убираем до подключения
  forceStopWireGuard(isDev, __dirname, () => {})

  if (process.defaultApp) {
    if (process.argv.length >= 2) {
      app.setAsDefaultProtocolClient('silentvpn', process.execPath, [path.resolve(process.argv[1])])
    }
  } else {
    app.setAsDefaultProtocolClient('silentvpn')
  }
  createWindow()
  createTray()
})

app.on('before-quit', () => {
  isQuitting = true
  cleanupVpn()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
