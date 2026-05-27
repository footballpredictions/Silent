const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell, clipboard } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')

// Self-signed сервер — как на Android (TrustAllCerts)
app.commandLine.appendSwitch('ignore-certificate-errors')
const {
  stopWireGuardTunnel,
  forceStopWireGuard,
  isProcessElevated,
  buildWgConfigFromApi,
  applyWireGuardConfig,
} = require('./vpn/wireguard')

const isDev = process.env.NODE_ENV === 'development'
const WIN_WIDTH = 265
const WIN_HEIGHT = 606

let mainWindow = null
let tray = null
let isQuitting = false
let wdttProcess = null
let wgApplied = false
let pendingVkDeepLink = null

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
  if (wdttProcess) {
    try { wdttProcess.kill() } catch {}
    wdttProcess = null
  }
  stopWireGuardTunnel(isDev, __dirname, sendLog)
  wgApplied = false
}

function wdttExePath() {
  const p = isDev
    ? path.join(__dirname, '../../resources/wdtt-client.exe')
    : path.join(process.resourcesPath, 'wdtt-client.exe')
  return p
}

ipcMain.handle('window-minimize', () => mainWindow?.minimize())
ipcMain.handle('window-close', () => mainWindow?.hide())
ipcMain.handle('open-external', (_, url) => shell.openExternal(url))
ipcMain.handle('get-platform', () => process.platform)

ipcMain.handle('clipboard-write', (_, text) => {
  clipboard.writeText(String(text ?? ''))
  return true
})

ipcMain.handle('vpn-connect', async (_, config) => {
  if (wdttProcess) return { error: 'Already running' }

  const exePath = wdttExePath()
  if (!fs.existsSync(exePath)) {
    return { error: `wdtt-client.exe не найден: ${exePath}` }
  }

  const tmpDir = app.getPath('temp')
  const confPath = path.join(tmpDir, 'wg-turn.conf')
  if (fs.existsSync(confPath)) fs.unlinkSync(confPath)

  const hashes = (config.vk_hashes || []).filter(Boolean).join(',')
  const args = [
    '-peer', `${config.server_ip}:${config.server_port}`,
    '-vk', hashes,
    '-password', config.wdtt_password,
    '-device-id', String(config.device_id || ''),
    '-listen', '127.0.0.1:9000',
    '-n', String(config.stream_count || 12),
    '-captcha-mode', 'auto',
  ]

  wdttProcess = spawn(exePath, args, { cwd: tmpDir })
  wgApplied = false

  const excludeIPs = new Set()
  if (config.server_ip) excludeIPs.add(config.server_ip)
  const apiConf = buildWgConfigFromApi(config)

  let wgAttempted = false
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
    if (wgApplied || !wgAttempted) return
    clearWgRetries()
    sendVpnError(msg)
    cleanupVpn()
  }

  const tryApplyWg = async (confText) => {
    if (wgApplied || wgAttempted || !confText) return false
    wgAttempted = true
    clearWgRetries()

    fs.writeFileSync(confPath, confText)
    await new Promise(r => setTimeout(r, 400))
    const ok = await applyWireGuardConfig(confPath, isDev, __dirname, sendLog, [...excludeIPs])
    if (ok) {
      wgApplied = true
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('vpn-ready', true)
      }
      return true
    }
    failWireGuard(
      isProcessElevated()
        ? 'WireGuard не запустился. Откройте services.msc → WireGuardTunnel$wg-turn или переустановите WireGuard с wireguard.com.'
        : 'WireGuard требует права администратора. Закройте Silent VPN полностью (ПКМ в трее → Выход), запустите ярлык «Запуск от имени администратора» и подключитесь снова.',
    )
    return false
  }

  const applyFromFile = async () => {
    if (!fs.existsSync(confPath)) return false
    const text = fs.readFileSync(confPath, 'utf8')
    if (text.includes('[Interface]')) return tryApplyWg(text)
    return false
  }

  const handleLine = async (line) => {
    sendLog(line)
    const turnMatch = line.match(/TURN UDP \(([\d.]+):\d+\)/)
    if (turnMatch) excludeIPs.add(turnMatch[1])

    if (line.includes('[ДИСП] Воркер') && line.includes('зарегистрирован')) {
      if (!wgApplied && !wgAttempted && apiConf) await tryApplyWg(apiConf)
    }

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
      if (cfg) await tryApplyWg(cfg)
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
    stopWireGuardTunnel(isDev, __dirname, sendLog)
    wgApplied = false
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-stopped', code)
    }
  })

  wgPoll = setInterval(async () => {
    if (wgApplied || wgAttempted) { clearWgRetries(); return }
    await applyFromFile()
  }, 3000)

  wgTimers.push(setTimeout(async () => {
    if (!wgApplied && !wgAttempted && apiConf) await tryApplyWg(apiConf)
  }, 20000))

  return { success: true }
})

ipcMain.handle('vpn-disconnect', async () => {
  cleanupVpn()
  return { success: true }
})

ipcMain.handle('vpn-read-config', async () => {
  const confPath = path.join(app.getPath('temp'), 'wg-turn.conf')
  return fs.existsSync(confPath) ? fs.readFileSync(confPath, 'utf8') : null
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
