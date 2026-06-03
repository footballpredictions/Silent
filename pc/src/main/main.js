const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, clipboard } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')

// Self-signed сервер — как на Android (TrustAllCerts)
app.commandLine.appendSwitch('ignore-certificate-errors')
const {
  stopWireGuardTunnel,
  forceStopWireGuard,
  waitForWdttProxy,
  waitForTunnelDown,
  isProcessElevated,
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
let networkMonitor = null
let wdttRelaunchTimer = null

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

function sendLog(line) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('vpn-log', line)
  }
}

function cleanupVpn() {
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
}

function isWdttAlive() {
  if (!wdttProcess) return false
  try {
    return wdttProcess.exitCode === null && !wdttProcess.killed
  } catch {
    return false
  }
}

function isTransportHealthy() {
  return wgApplied && activeWorkerCount >= 1 && isWdttAlive()
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
  if (!vpnSessionActive || !lastVpnConnectConfig || wdttProcess) return
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
  const exePath = wdttExePath()
  if (!fs.existsSync(exePath)) {
    return { error: `wdtt-client.exe не найден: ${exePath}` }
  }

  const tmpDir = app.getPath('temp')
  const confPath = path.join(tmpDir, 'wg-turn.conf')
  if (!switching && fs.existsSync(confPath)) fs.unlinkSync(confPath)

  const hashes = (config.vk_hashes || []).filter(Boolean).join(',')
  const workers = Math.min(Math.max(Number(config.stream_count) || 108, 9), 108)
  sendLog(`[VPN] connect n=${workers} hashes=${(config.vk_hashes || []).filter(Boolean).length}`)
  const args = [
    '-peer', `${config.server_ip}:${config.server_port}`,
    '-vk', hashes,
    '-password', config.wdtt_password,
    '-device-id', String(config.device_id || ''),
    '-listen', '127.0.0.1:9000',
    '-n', String(workers),
    '-captcha-mode', 'auto',
  ]

  wdttProcess = spawn(exePath, args, { cwd: tmpDir })
  if (!switching) {
    wgApplied = false
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
    wgAttempted = true
    clearWgRetries()

    sendLog(`[WG] Применение конфига (${source})...`)
    sendLog('[WG] Ожидание WDTT UDP 127.0.0.1:9000...')
    const wdttReady = await waitForWdttProxy('127.0.0.1', 9000, 30000, sendLog, confPath)
    if (!wdttReady) {
      wgInstallInFlight = false
      wgAttempted = false
      failWireGuard('Таймаут: WDTT не подключился к серверу')
      return false
    }

    fs.writeFileSync(confPath, normalizedConf)
    await sleep(150)

    const wgPromise = applyWireGuardConfig(confPath, isDev, __dirname, sendLog, [...excludeIPs], { skipWdttWait: true })
    const timeoutMs = isProcessElevated() ? 35000 : 90000
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
    if (ok) {
      wgApplied = true
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('vpn-ready', true)
      }
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
    sendLog(line)
    const statsMatch = line.match(/Активных:\s*(\d+)/)
    if (statsMatch) activeWorkerCount = parseInt(statsMatch[1], 10)
    const regMatch = line.match(/зарегистрирован \(всего:\s*(\d+)\)/)
    if (regMatch) activeWorkerCount = parseInt(regMatch[1], 10)
    const turnMatch = line.match(/TURN UDP \(([\d.]+):\d+\)/)
    if (turnMatch) excludeIPs.add(turnMatch[1])

    if (line.includes('[КОНФИГ]') && line.includes('Сохранён')) {
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
      if (cfg) await tryApplyWg(cfg, 'box')
      return
    }
    if (line.includes('║')) {
      const c = line.replace(/║/g, '').trim()
      if (c) boxBuilder.push(c)
    }
  }

  wdttProcess.stdout.on('data', (d) => {
    d.toString().split('\n').forEach(l => {
      if (!l) return
      handleLine(l)
      parseBox(l)
    })
  })
  wdttProcess.stderr.on('data', (d) => {
    d.toString().split('\n').forEach(l => { if (l) handleLine(l) })
  })

  wdttProcess.on('close', (code) => {
    clearWgRetries()
    wdttProcess = null
    activeWorkerCount = 0
    if (vpnSessionActive && wgApplied && !isQuitting) {
      sendLog(`[VPN] wdtt завершился (code=${code}), WG остаётся — перезапуск транспорта…`)
      transportSwitching = true
      scheduleWdttRelaunch(1500)
      return
    }
    stopWireGuardTunnel(isDev, __dirname, sendLog)
    wgApplied = false
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-stopped', code)
    }
  })

  if (switching && wgApplied) {
    return { success: true }
  }

  wgPoll = setInterval(async () => {
    if (wgApplied || wgFailed || wgAttempted || wgInstallInFlight) {
      if (wgApplied || wgFailed) clearWgRetries()
      return
    }
    await applyFromFile()
  }, 2000)

  wgTimers.push(setTimeout(async () => {
    if (wgApplied || wgFailed || wgAttempted || wgInstallInFlight) return
    if (apiConf) await tryApplyWg(apiConf, 'api')
  }, 20000))

  return { success: true }
}

ipcMain.handle('vpn-connect', async (_, config) => {
  if (wdttProcess && !transportSwitching) {
    sendLog('[VPN] Переподключение: остановка предыдущей сессии...')
    await cleanupVpnAsync()
  } else if (!wdttProcess) {
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
})

ipcMain.handle('vpn-disconnect', async () => {
  await cleanupVpnAsync()
  return { success: true }
})

ipcMain.handle('vpn-read-config', async () => {
  const confPath = path.join(app.getPath('temp'), 'wg-turn.conf')
  return fs.existsSync(confPath) ? fs.readFileSync(confPath, 'utf8') : null
})

ipcMain.handle('vpn-is-ready', async () => ({
  ready: !!wgApplied,
  workers: activeWorkerCount,
}))

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
