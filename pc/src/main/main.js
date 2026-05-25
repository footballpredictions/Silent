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

// Generate AllowedIPs that cover 0.0.0.0/0 EXCEPT the specified IPs.
// This is the correct WireGuard split-tunnel method: prevents WFP from blocking DTLS/TURN traffic.
function generateExclusionAllowedIPs(excludeIPs) {
  const ipToNum = ip => ip.split('.').reduce((a, b) => (a << 8 | Number(b)) >>> 0, 0)
  const numToIp = n => [(n>>>24)&0xff,(n>>>16)&0xff,(n>>>8)&0xff,n&0xff].join('.')

  function cidrExclude(netNum, prefix, excludeNum) {
    const mask = prefix === 0 ? 0 : ((0xffffffff << (32 - prefix)) >>> 0)
    if ((excludeNum & mask) !== (netNum & mask)) return [[netNum, prefix]]
    if (prefix === 32) return []
    const np = prefix + 1
    const nm = ((0xffffffff << (32 - np)) >>> 0)
    const left = netNum
    const right = (netNum | (1 << (31 - prefix))) >>> 0
    if ((excludeNum & nm) === (left & nm))
      return [...cidrExclude(left, np, excludeNum), [right, np]]
    return [[left, np], ...cidrExclude(right, np, excludeNum)]
  }

  let networks = [[0, 0]]
  for (const ip of excludeIPs) {
    const excl = ipToNum(ip)
    const next = []
    for (const [net, pfx] of networks) next.push(...cidrExclude(net, pfx, excl))
    networks = next
  }
  return networks.map(([n, p]) => `${numToIp(n)}/${p}`).join(', ')
}

// Apply wg-turn.conf via WireGuard Windows CLI (requires admin)
async function applyWireGuardConfig(confPath, send, excludeIPs = []) {
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

  // Patch AllowedIPs to exclude TURN/server IPs.
  // This prevents WireGuard WFP from blocking wdtt-client DTLS traffic to TURN servers.
  if (excludeIPs.length > 0) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      const allowedIPs = generateExclusionAllowedIPs(excludeIPs)
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${allowedIPs}`)
      fs.writeFileSync(confPath, conf)
      send(`[WG] Split-tunnel: исключено IP из AllowedIPs (${excludeIPs.length} хостов)`)
    } catch (e) {
      send('[WG] Предупреждение: не удалось патчить AllowedIPs: ' + e.message)
    }
  }

  // Remove existing tunnel first (ignore error)
  const { execSync } = require('child_process')
  try {
    execSync(`"${wgExe}" /uninstalltunnelservice wg-turn`, { windowsHide: true })
    await new Promise(r => setTimeout(r, 1500))
  } catch {}

  send('[WG] Применяю конфигурацию WireGuard...')
  const wgProc = spawn(wgExe, ['/installtunnelservice', confPath], {
    windowsHide: true,
    detached: false,
  })
  wgProc.on('close', async (code) => {
    if (code === 0) {
      send('[WG] ✅ WireGuard туннель активирован!')
      send('[WG] Трафик защищён, IP: 10.66.66.2')
    } else {
      send(`[WG] ⚠ Ошибка активации (код ${code})`)
      send('[WG] Убедитесь что приложение запущено от Администратора')
      return
    }

    // Diagnostic: check service state + handshake after 4 seconds
    await new Promise(r => setTimeout(r, 4000))
    try {
      // Check Windows service state
      const svcOut = execSync('sc query WireGuardTunnel$wg-turn', { windowsHide: true, encoding: 'utf8' })
      const state = (svcOut.match(/STATE\s*:\s*\d+\s+(\S+)/) || [])[1] || '?'
      send(`[WG] Сервис WireGuardTunnel: ${state}`)

      // Show tunnel status via wg.exe
      const wgDir = path.dirname(wgExe)
      const wgCli = path.join(wgDir, 'wg.exe')
      if (fs.existsSync(wgCli)) {
        const wgStatus = execSync(`"${wgCli}" show wg-turn`, { windowsHide: true, encoding: 'utf8' })
        send('[WG] wg show:')
        wgStatus.split('\n').filter(l => l.trim()).forEach(l => send('  ' + l.trim()))
      }

      // Ping VPN server
      const pingOut = execSync('ping -n 2 -w 2000 10.66.66.1', { windowsHide: true, encoding: 'utf8' })
      if (pingOut.includes('TTL=') || pingOut.includes('ttl=')) {
        send('[WG] ✅ Ping 10.66.66.1 — туннель работает!')
      } else {
        send('[WG] ⚠ Ping 10.66.66.1 нет ответа — handshake не завершён')
        send('[WG] Проверяю маршруты...')
        const routes = execSync('route print 10.66.66.*', { windowsHide: true, encoding: 'utf8' })
        routes.split('\n').filter(l => l.includes('10.66.66')).forEach(l => send('  ' + l.trim()))
      }
    } catch (e) {
      send('[WG] Диагностика: ' + e.message.split('\n')[0].slice(0, 120))
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

  // Collect TURN/server IPs to exclude from WireGuard AllowedIPs
  const excludeIPs = new Set()
  if (config.server_ip) excludeIPs.add(config.server_ip)

  let wgApplied = false
  let confSaved = false
  let activeWorkers = 0

  const tryApplyWg = async () => {
    if (wgApplied || !confSaved || activeWorkers < 2) return
    wgApplied = true
    // Extra 500ms to collect more TURN IPs from logs before patching conf
    await new Promise(r => setTimeout(r, 500))
    send(`[WG] Воркеров активно: ${activeWorkers}, запускаю туннель...`)
    await applyWireGuardConfig(confPath, send, [...excludeIPs])
  }

  const handleLine = async (line) => {
    send(line)
    // Collect TURN server IPs from logs: "[СЕССИЯ #N] TURN UDP (IP:PORT)"
    const turnMatch = line.match(/TURN UDP \(([\d.]+):\d+\)/)
    if (turnMatch) excludeIPs.add(turnMatch[1])

    if (line.includes('[КОНФИГ] Сохранён в wg-turn.conf')) {
      confSaved = true
      await tryApplyWg()
    }

    // Count active workers from dispatcher messages
    if (line.includes('[ДИСП] Воркер') && line.includes('зарегистрирован')) {
      const m = line.match(/всего:\s*(\d+)/)
      if (m) activeWorkers = parseInt(m[1])
      await tryApplyWg()
    }
  }

  wdttProcess.stdout.on('data', (d) => d.toString().split('\n').forEach(l => { if (l) handleLine(l) }))
  wdttProcess.stderr.on('data', (d) => d.toString().split('\n').forEach(l => { if (l) handleLine(l) }))

  wdttProcess.on('close', (code) => {
    wdttProcess = null
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
