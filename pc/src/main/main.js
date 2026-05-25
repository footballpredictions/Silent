const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain, shell } = require('electron')
const path = require('path')
const { spawn } = require('child_process')
const fs = require('fs')
const isDev = process.env.NODE_ENV === 'development'

let wdttProcess = null

// Window dimensions: ~7cm × 16cm at 96dpi = 265×606px
const WIN_WIDTH = 265
const WIN_HEIGHT = 606

let mainWindow = null
let tray = null
let isQuitting = false

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
    transparent: false,
    backgroundColor: '#ffffff',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
    icon: path.join(__dirname, '../../assets/icon.png'),
    title: 'Silent VPN',
    show: false,
    skipTaskbar: false,
  })

  if (isDev) {
    mainWindow.loadURL('http://localhost:3001')
    mainWindow.webContents.openDevTools({ mode: 'detach' })
  } else {
    mainWindow.loadFile(path.join(__dirname, '../../dist/renderer/index.html'))
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })

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
    { label: 'Выход', click: () => { isQuitting = true; app.quit() } },
  ])
  tray.setContextMenu(contextMenu)
  tray.on('click', () => {
    if (mainWindow.isVisible()) {
      mainWindow.hide()
    } else {
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

// IPC handlers
ipcMain.handle('window-minimize', () => mainWindow.minimize())
ipcMain.handle('window-close', () => mainWindow.hide())
ipcMain.handle('open-external', (_, url) => shell.openExternal(url))
ipcMain.handle('get-platform', () => process.platform)

// WireGuard helper: find wireguard.exe on Windows
function findWireGuard() {
  const candidates = [
    'C:\\Program Files\\WireGuard\\wireguard.exe',
    'C:\\Program Files (x86)\\WireGuard\\wireguard.exe',
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return null
}

// Silently install WireGuard from bundled MSI
async function installWireGuard(send) {
  const resourcesDir = isDev
    ? path.join(__dirname, '../../resources')
    : process.resourcesPath

  // Try .msi first, then .exe
  const msiPath = path.join(resourcesDir, 'wireguard-installer.msi')
  const exePath = path.join(resourcesDir, 'wireguard-installer.exe')
  const installerPath = fs.existsSync(msiPath) ? msiPath : fs.existsSync(exePath) ? exePath : null

  if (!installerPath) {
    send('[WG] ❌ Установщик WireGuard не найден в ресурсах')
    return false
  }

  send('[WG] Устанавливаю WireGuard (20–30 секунд)...')

  const pollForWg = async (seconds) => {
    for (let i = 0; i < seconds; i++) {
      await new Promise(r => setTimeout(r, 1000))
      if (findWireGuard()) return true
    }
    return false
  }

  return new Promise(async (resolve) => {
    const isMsi = installerPath.endsWith('.msi')

    // Try direct install first (works if already admin)
    const proc = isMsi
      ? spawn('msiexec', ['/i', installerPath, '/quiet', '/norestart'], { windowsHide: true })
      : spawn(installerPath, ['/S'], { windowsHide: true })

    proc.on('close', async () => {
      if (await pollForWg(20)) {
        send('[WG] ✅ WireGuard установлен')
        resolve(true)
        return
      }

      // Fallback: try via PowerShell RunAs (triggers UAC prompt)
      send('[WG] Запрашиваю права администратора...')
      const psArgs = isMsi
        ? `msiexec -ArgumentList '/i \\"${installerPath.replace(/\\/g, '\\\\')}\\" /quiet /norestart'`
        : `'${installerPath.replace(/\\/g, '\\\\')}' -ArgumentList '/S'`
      const psCmd = `Start-Process ${psArgs} -Verb RunAs -Wait`
      const elevated = spawn('powershell', ['-WindowStyle', 'Hidden', '-Command', psCmd])
      elevated.on('close', async () => {
        if (await pollForWg(20)) {
          send('[WG] ✅ WireGuard установлен')
          resolve(true)
        } else {
          send('[WG] ⚠ Установка не удалась. Скачайте вручную: wireguard.com/install')
          resolve(false)
        }
      })
    })
  })
}

// Get original default gateway before VPN changes routing
function getDefaultGateway() {
  const { execSync } = require('child_process')
  try {
    const out = execSync('route print 0.0.0.0', { windowsHide: true, encoding: 'utf8' })
    const match = out.match(/0\.0\.0\.0\s+0\.0\.0\.0\s+([\d.]+)/)
    return match ? match[1] : null
  } catch { return null }
}

// Add host route for an IP via a specific gateway (so it bypasses VPN)
function addExclusionRoute(ip, gateway) {
  const { execSync } = require('child_process')
  try { execSync(`route add ${ip} mask 255.255.255.255 ${gateway} metric 1`, { windowsHide: true }) } catch {}
}

function delExclusionRoute(ip) {
  const { execSync } = require('child_process')
  try { execSync(`route delete ${ip} mask 255.255.255.255`, { windowsHide: true }) } catch {}
}

// Apply wg-turn.conf via WireGuard Windows CLI (requires admin)
async function applyWireGuardConfig(confPath, send, turnIPs = [], gateway = null) {
  let wgExe = findWireGuard()

  // Auto-install if not found
  if (!wgExe) {
    const ok = await installWireGuard(send)
    if (!ok) {
      send('[WG] Конфиг сохранён в: ' + confPath)
      return
    }
    wgExe = findWireGuard()
  }

  if (!wgExe) return

  // Add exclusion routes for TURN server IPs BEFORE activating VPN
  // This prevents routing loop: wdtt-client traffic bypasses the WireGuard tunnel
  if (gateway && turnIPs.length > 0) {
    send(`[WG] Маршруты для TURN серверов через шлюз ${gateway}...`)
    for (const ip of turnIPs) {
      addExclusionRoute(ip, gateway)
      send(`[WG] route add ${ip} → ${gateway}`)
    }
  }

  // Remove existing tunnel first (ignore error)
  const { execSync } = require('child_process')
  try {
    execSync(`"${wgExe}" /uninstalltunnelservice wg-turn`, { windowsHide: true })
    await new Promise(r => setTimeout(r, 1000))
  } catch {}

  send('[WG] Применяю конфигурацию WireGuard...')
  const wgProc = spawn(wgExe, ['/installtunnelservice', confPath], {
    windowsHide: true,
    detached: false,
  })
  wgProc.on('close', (code) => {
    if (code === 0) {
      send('[WG] ✅ WireGuard туннель активирован!')
      send('[WG] Трафик защищён, IP: 10.66.66.2')
    } else {
      send(`[WG] ⚠ Ошибка активации (код ${code})`)
      send('[WG] Убедитесь что приложение запущено от Администратора')
    }
  })
}

ipcMain.handle('vpn-connect', async (_, config) => {
  if (wdttProcess) return { error: 'Already running' }

  const exePath = isDev
    ? path.join(__dirname, '../../resources/wdtt-client.exe')
    : path.join(process.resourcesPath, 'wdtt-client.exe')

  if (!fs.existsSync(exePath)) {
    return { error: `wdtt-client.exe not found: ${exePath}` }
  }

  const tmpDir = app.getPath('temp')
  const confPath = path.join(tmpDir, 'wg-turn.conf')
  if (fs.existsSync(confPath)) fs.unlinkSync(confPath)

  const args = [
    '-peer', `${config.server_ip}:${config.server_port}`,
    '-vk', config.vk_hashes.join(','),
    '-password', config.wdtt_password,
    '-device-id', config.device_id,
    '-listen', '127.0.0.1:9000',
    '-n', '12',
    '-captcha-mode', 'rjs',
  ]

  wdttProcess = spawn(exePath, args, { cwd: tmpDir })

  const send = (line) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-log', line)
    }
  }

  // Capture gateway before VPN changes routing
  const originalGateway = getDefaultGateway()
  // Also always exclude the VPN server IP itself
  const turnIPs = new Set()
  if (config.server_ip) turnIPs.add(config.server_ip)

  let wgApplied = false

  const handleLine = async (line) => {
    send(line)
    // Collect TURN relay IPs from wdtt-client logs: "[СЕССИЯ #N] TURN UDP (IP:PORT)"
    const turnMatch = line.match(/TURN UDP \(([\d.]+):\d+\)/)
    if (turnMatch) turnIPs.add(turnMatch[1])

    // When conf saved — add exclusion routes then activate WireGuard
    if (!wgApplied && line.includes('[КОНФИГ] Сохранён в wg-turn.conf')) {
      wgApplied = true
      await new Promise(r => setTimeout(r, 500))
      await applyWireGuardConfig(confPath, send, [...turnIPs], originalGateway)
    }
  }

  wdttProcess.stdout.on('data', (d) => d.toString().split('\n').forEach(l => { if (l) handleLine(l) }))
  wdttProcess.stderr.on('data', (d) => d.toString().split('\n').forEach(l => { if (l) handleLine(l) }))

  wdttProcess.on('close', (code) => {
    wdttProcess = null
    // Remove exclusion routes
    for (const ip of turnIPs) delExclusionRoute(ip)
    // Remove WireGuard tunnel
    const wgExe = findWireGuard()
    if (wgExe) {
      try { require('child_process').execSync(`"${wgExe}" /uninstalltunnelservice wg-turn`, { windowsHide: true }) } catch {}
    }
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('vpn-stopped', code)
    }
  })

  return { success: true }
})

ipcMain.handle('vpn-disconnect', async () => {
  if (wdttProcess) { wdttProcess.kill(); wdttProcess = null }
  return { success: true }
})

ipcMain.handle('vpn-read-config', async () => {
  const confPath = path.join(app.getPath('temp'), 'wg-turn.conf')
  return fs.existsSync(confPath) ? fs.readFileSync(confPath, 'utf8') : null
})

app.whenReady().then(() => {
  createWindow()
  createTray()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
