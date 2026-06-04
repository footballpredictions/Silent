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
let wdttGeneration = 0
let wdttReplacing = false

const { createNetworkMonitor } = require('./vpn/networkRecovery')

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
    if (url) handleVkDeepLink(url)
  })
}

function handleVkDeepLink(url) {
  if (!url || typeof url !== 'string' || !url.startsWith('silentvpn://')) return
  try {
    const u = new URL(url)
    if (u.hostname !== 'vk-linked') return
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
  } catch {}
}

if (process.platform === 'win32') {
  const launchUrl = process.argv.find(a => typeof a === 'string' && a.startsWith('silentvpn://'))
  if (launchUrl) handleVkDeepLink(launchUrl)
}

app.on('open-url', (event, url) => {
  event.preventDefault()
  handleVkDeepLink(url)
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
    icon: path.join(__dirname, '../../assets/icon.png'),
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
  const iconPath = path.join(__dirname, '../../assets/tray.png')
  const icon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 })
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

function formatVpnLogLine(line) {
  if (!line || typeof line !== 'string') return line
  if (line.startsWith('CAPTCHA_SOLVE|')) {
    const parts = line.split('|')
    const mode = parts[1] || 'auto'
    const n = (parts[2] || '').length + (parts[3] || '').length
    return `[VPN] CAPTCHA: окно браузера (${mode}, ~${n} симв. токена)`
  }
  const noisyWorker = line.includes('[ВОРКЕР #')
    && !line.includes('[READY]')
    && !line.includes('зарегистрирован')
    && !line.includes('Ошибка')
  if (
    line.includes('[СЕССИЯ #')
    || line.includes('[DTLS]')
    || line.includes('Рукопожатие')
    || noisyWorker
  ) {
    return null
  }
  return line
}

function sendLog(line) {
  const formatted = formatVpnLogLine(line)
  if (!formatted) return
  line = formatted
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('vpn-log', line)
  }
}

function cleanupVpn() {
  vpnBootstrapMode = false
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

/** PC: WG после ≥6 воркеров (9 на 0.0.0.0/0 мало для десктопа). Bootstrap: 1. */
function minWorkersForTunnelReady(isBootstrap = false) {
  if (isBootstrap || vpnBootstrapMode) return 1
  return 6
}

function isVpnReadyForUi() {
  if (tunnelReadySent) return true
  if (!wgApplied) return false
  return activeWorkerCount >= minWorkersForTunnelReady(vpnBootstrapMode)
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
  scheduleWdttRelaunch(1500)
}

function scheduleWdttRelaunch(delayMs = 1500) {
  if (!vpnSessionActive || !lastVpnConnectConfig) return
  if (wdttProcess && isWdttAlive()) return
  if (wdttRelaunchTimer) clearTimeout(wdttRelaunchTimer)
  wdttRelaunchTimer = setTimeout(() => {
    wdttRelaunchTimer = null
    if (!vpnSessionActive || wdttProcess || !lastVpnConnectConfig) return
    transportSwitching = true
    sendLog('[VPN] Перезапуск wdtt-client…')
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
  await waitForTunnelDown(4000, sendLog)
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

  const hashes = (config.vk_hashes || []).filter(Boolean).join(',')
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
    clearWgRetries()

    sendLog(`[WG] Применение конфига (${source})...`)
    sendLog('[WG] Ожидание WDTT UDP 127.0.0.1:9000...')
    const proxyWaitMs = switching ? 12_000 : 30_000
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
      // Bootstrap: только 10.66.66.0/24. Основной VPN: 0.0.0.0/0 — на белых списках YouTube только через туннель.
      subnetOnly: vpnBootstrapMode,
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
    if (text.includes('[Interface]')) return tryApplyWg(text, 'wdtt-file')
    return false
  }

  const handleLine = async (line) => {
    const statsMatch = line.match(/Активных:\s*(\d+)/)
    if (statsMatch) {
      activeWorkerCount = parseInt(statsMatch[1], 10)
      if (wgApplied) ensureVpnReadyEvent(sendLog)
      const now = Date.now()
      if (now - lastStatsLogToUiAt < 8000) return
      lastStatsLogToUiAt = now
    }
    sendLog(line)
    const regMatch = line.match(/зарегистрирован \(всего:\s*(\d+)\)/)
    if (regMatch) {
      activeWorkerCount = parseInt(regMatch[1], 10)
      if (wgApplied) ensureVpnReadyEvent(sendLog)
    }
    // TURN IP в AllowedIPs не добавляем: split 0.0.0.0/0 → сотни маршрутов, WG на Windows падает (exit 10).

    if (!switching && line.includes('[КОНФИГ]') && line.includes('Сохранён')) {
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
      scheduleWdttRelaunch(1500)
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

  // Запасной конфиг с сервера — только bootstrap; основной VPN как Android (только wdtt/box).
  if (config.is_bootstrap && apiConf) {
    wgTimers.push(setTimeout(async () => {
      if (wgApplied || wgFailed || wgInstallInFlight) return
      await tryApplyWg(apiConf, 'api-fallback')
    }, 8000))
  }

  return { success: true }
}

ipcMain.handle('vpn-connect', async (_, config) => {
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
    if (!result.error) startNetworkMonitor()
    return result
  } finally {
    vpnConnectInFlight = false
  }
})

ipcMain.handle('vpn-disconnect', async (_, opts) => {
  if (opts?.fast) {
    await fastDisconnectVpn()
    return { success: true }
  }
  await cleanupVpnAsync()
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
