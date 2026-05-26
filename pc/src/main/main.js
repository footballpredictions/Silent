const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')
const {
  stopWireGuardTunnel,
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
  stopWireGuardTunnel(isDev, __dirname)
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
  let activeWorkers = 0
  const apiConf = buildWgConfigFromApi(config)

  const sendVpnError = (msg) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-error', msg)
    }
  }

  const tryApplyWg = async (confText) => {
    if (wgApplied || !confText) return false
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
    sendVpnError('WireGuard: запустите Silent VPN от администратора')
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

    if (line.includes('[СТАТИСТИКА]')) {
      const m = line.match(/Активных:\s*(\d+)/)
      if (m) activeWorkers = parseInt(m[1], 10)
    }
    if (line.includes('[ДИСП] Воркер') && line.includes('зарегистрирован')) {
      const m = line.match(/всего:\s*(\d+)/)
      if (m) activeWorkers = parseInt(m[1], 10)
      if (!wgApplied && apiConf) await tryApplyWg(apiConf)
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

  let confPoll = null

  wdttProcess.on('close', (code) => {
    if (confPoll) clearInterval(confPoll)
    wdttProcess = null
    stopWireGuardTunnel(isDev, __dirname)
    wgApplied = false
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-stopped', code)
    }
  })

  confPoll = setInterval(async () => {
    if (wgApplied) { clearInterval(confPoll); return }
    await applyFromFile()
  }, 2000)

  for (const ms of [3000, 8000, 15000]) {
    setTimeout(async () => {
      if (!wgApplied && apiConf) await tryApplyWg(apiConf)
    }, ms)
  }

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
