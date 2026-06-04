/**
 * WireGuard Windows: wireguard.exe + wintun.dll bundled в PC-клиенте (resources/wireguard/).
 * Устанавливает службу WireGuardTunnel$wg-turn через /installtunnelservice.
 */
const path = require('path')
const fs = require('fs')
const os = require('os')
const net = require('net')
const { execSync, execFileSync, spawn } = require('child_process')

const TUNNEL_NAME = 'wg-turn'
const TUNNEL_CONF_NAME = 'wg-turn.conf'
const SERVICE_NAME = `WireGuardTunnel$${TUNNEL_NAME}`
const STABLE_CONF_DIR = path.join(process.env.ProgramData || 'C:\\ProgramData', 'SilentVPN')
const STABLE_WG_DIR = path.join(STABLE_CONF_DIR, 'wireguard')

let lastRuntimeDir = null

function resourcesDir(isDev, dirname) {
  return isDev ? path.join(dirname, '../../resources') : process.resourcesPath
}

const SYSTEM_WG_DIR = 'C:\\Program Files\\WireGuard'

function findBundledDir(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    path.join(base, 'wireguard'),
    path.join(STABLE_WG_DIR),
    SYSTEM_WG_DIR,
    base,
  ]
  for (const dir of candidates) {
    if (fs.existsSync(path.join(dir, 'wireguard.exe'))) return dir
  }
  return null
}

function findWintunDll(dir) {
  if (!dir) return null
  const p = path.join(dir, 'wintun.dll')
  return fs.existsSync(p) ? p : null
}

function isProcessElevated() {
  try {
    execSync('net session', { stdio: 'ignore', windowsHide: true })
    return true
  } catch {
    return false
  }
}

/** Копируем wireguard.exe + wintun.dll в ProgramData — служба Windows не должна ссылаться на %TEMP%. */
function prepareRuntimeDir(isDev, dirname, send) {
  const bundled = findBundledDir(isDev, dirname)
  let srcDir = bundled
  let wintunSrc = findWintunDll(bundled)

  if (!srcDir || !wintunSrc) {
    if (fs.existsSync(path.join(SYSTEM_WG_DIR, 'wireguard.exe'))) {
      srcDir = SYSTEM_WG_DIR
      wintunSrc = findWintunDll(SYSTEM_WG_DIR)
      send?.('[WG] Используем WireGuard из Program Files')
    }
  }

  if (!srcDir || !wintunSrc) {
    send?.('[WG] Не найдены wireguard.exe / wintun.dll (resources/wireguard или установка WireGuard)')
    return null
  }

  fs.mkdirSync(STABLE_WG_DIR, { recursive: true })
  for (const name of ['wireguard.exe', 'wg.exe']) {
    const src = path.join(srcDir, name)
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, path.join(STABLE_WG_DIR, name))
    }
  }
  fs.copyFileSync(wintunSrc, path.join(STABLE_WG_DIR, 'wintun.dll'))
  lastRuntimeDir = STABLE_WG_DIR
  send?.(`[WG] Runtime: ${STABLE_WG_DIR}`)
  return STABLE_WG_DIR
}

function runCmd(cmd, cwd) {
  try {
    return execSync(cmd, { cwd, encoding: 'utf8', windowsHide: true, timeout: 45000, stdio: 'pipe' })
  } catch (e) {
    const out = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim()
    return out || null
  }
}

function runWgInstall(wgExe, stableConf, runtimeDir, send) {
  send('[WG] Установка службы WireGuardTunnel$wg-turn...')
  runCmd(`"${wgExe}" /uninstalltunnelservice ${TUNNEL_NAME}`, runtimeDir)
  const installOut = runCmd(`"${wgExe}" /installtunnelservice "${stableConf}"`, runtimeDir)
  if (installOut) send('[WG] install: ' + installOut.slice(0, 300))

  try {
    execSync(`sc start "${SERVICE_NAME}"`, { windowsHide: true, stdio: 'pipe', timeout: 20000, encoding: 'utf8' })
  } catch (e) {
    const msg = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim()
    // 1056 = служба уже запущена (installtunnelservice часто стартует сам)
    if (msg && !/1056|already running|уже запущен/i.test(msg)) {
      send('[WG] sc start: ' + msg.slice(0, 200))
    }
  }
}

function psExec(script) {
  const file = path.join(os.tmpdir(), `silent-wg-${Date.now()}.ps1`)
  try {
    fs.writeFileSync(file, script, 'utf8')
    execSync(`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${file}"`, {
      windowsHide: true,
      stdio: 'ignore',
      timeout: 30000,
    })
  } catch {} finally {
    try { fs.unlinkSync(file) } catch {}
  }
}

function isTunnelUp() {
  try {
    const out = execSync(
      'powershell.exe -NoProfile -Command "Get-NetAdapter -EA SilentlyContinue | ? { ($_.Name -eq \'wg-turn\' -or $_.InterfaceDescription -match \'WireGuard Tunnel\') -and $_.Status -eq \'Up\' } | Select -First 1 -Expand Name"',
      { windowsHide: true, encoding: 'utf8', timeout: 10000 },
    )
    return !!out.trim()
  } catch {
    return false
  }
}

/** STATE : 4 = Running (текст локализован на RU Windows). */
function isServiceRunning() {
  try {
    const out = execSync(`sc query "${SERVICE_NAME}"`, { encoding: 'utf8', windowsHide: true })
    if (/\bSTATE\s*:\s*4\b/i.test(out) || /\bСостояние\s*:\s*4\b/i.test(out)) return true
    return /\bRUNNING\b/i.test(out) || /\bРАБОТАЕТ\b/i.test(out)
  } catch {
    return false
  }
}

/** Профиль Private — стабильнее маршруты/DNS на Windows (иконка в трее всё равно от Wi‑Fi). */
function polishWgNetworkProfile(send) {
  try {
    execSync(
      `powershell.exe -NoProfile -Command "& { $a = Get-NetAdapter -EA SilentlyContinue | Where-Object { $_.Name -eq '${TUNNEL_NAME}' -or $_.InterfaceDescription -match 'WireGuard' } | Select-Object -First 1; if ($a) { Set-NetConnectionProfile -InterfaceIndex $a.ifIndex -NetworkCategory Private -ErrorAction SilentlyContinue } }"`,
      { windowsHide: true, timeout: 12000 },
    )
    send?.('[WG] Адаптер wg-turn: профиль Private')
  } catch { /* ignore */ }
}

function logServiceState(send) {
  try {
    const out = execSync(`sc query "${SERVICE_NAME}"`, { encoding: 'utf8', windowsHide: true })
    const state = (out.match(/STATE\s*:\s*\d+\s+(\S+)/) || [])[1] || '?'
    send(`[WG] Служба ${SERVICE_NAME}: ${state}`)
  } catch {
    send(`[WG] Служба ${SERVICE_NAME} не найдена`)
  }
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

async function waitForTunnelUp(maxMs = 30000, send) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    if (isTunnelUp() || isServiceRunning()) return true
    await sleep(500)
  }
  const up = isTunnelUp() || isServiceRunning()
  if (!up) logServiceState(send)
  return up
}

async function waitForTunnelDown(maxMs = 15000, send) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    if (!isTunnelUp() && !isServiceRunning()) return true
    await sleep(400)
  }
  const down = !isTunnelUp() && !isServiceRunning()
  if (!down) logServiceState(send)
  return down
}

/** WDTT/WireGuard слушает UDP :9000, не TCP. */
function isUdpPortListening(port, host = '127.0.0.1') {
  try {
    const out = execSync('netstat -ano -p udp', { encoding: 'utf8', windowsHide: true, timeout: 8000 })
    const portSuffix = `:${port}`
    return out.split('\n').some(line => {
      if (!line.includes(portSuffix)) return false
      const local = line.trim().split(/\s+/)[1] || ''
      return local.startsWith(host) || local.startsWith('0.0.0.0') || local === `[::]:${port}` || local === `*:${port}`
    })
  } catch {
    return false
  }
}

function waitForPort(host, port, timeoutMs = 8000) {
  return waitForWdttProxy(host, port, timeoutMs)
}

/** Ждём локальный WDTT-прокси (UDP 9000) или готовый wg-turn.conf. */
async function waitForWdttProxy(host, port, timeoutMs = 60000, send, confPath = null) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (confPath && fs.existsSync(confPath)) {
      try {
        const text = fs.readFileSync(confPath, 'utf8')
        if (text.includes('[Interface]') && text.includes(`127.0.0.1:${port}`)) {
          send?.('[WG] WDTT: конфиг wg-turn.conf готов')
          return true
        }
      } catch { /* ignore */ }
    }
    if (isUdpPortListening(port, host)) {
      send?.('[WG] WDTT: UDP прокси слушает ' + host + ':' + port)
      return true
    }
    await sleep(200)
  }
  send?.('[WG] WDTT: таймаут ожидания UDP ' + host + ':' + port)
  return false
}

function copyStableConf(confPath) {
  fs.mkdirSync(STABLE_CONF_DIR, { recursive: true })
  const stable = path.join(STABLE_CONF_DIR, TUNNEL_CONF_NAME)
  fs.copyFileSync(confPath, stable)
  return stable
}

function forceStopWireGuard(isDev, dirname, send) {
  send?.('[WG] Остановка туннеля...')

  const runtimeDir = lastRuntimeDir || prepareRuntimeDir(isDev, dirname, send) || STABLE_WG_DIR
  const wgExe = path.join(runtimeDir, 'wireguard.exe')

  if (fs.existsSync(wgExe)) {
    runCmd(`"${wgExe}" /uninstalltunnelservice ${TUNNEL_NAME}`, runtimeDir)
  }

  try { execSync(`sc stop "${SERVICE_NAME}"`, { windowsHide: true, stdio: 'ignore' }) } catch {}
  try { execSync(`sc delete "${SERVICE_NAME}"`, { windowsHide: true, stdio: 'ignore' }) } catch {}

  psExec(`
    Get-CimInstance Win32_Process -Filter "Name='wireguard.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -match 'wg-turn|SilentVPN|SilentVPN' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  `)

  send?.('[WG] Туннель остановлен')
}

function stopWireGuardTunnel(isDev, dirname, send) {
  forceStopWireGuard(isDev, dirname, send)
}

function buildWgConfigFromApi(config, listenPort = 9000) {
  const priv = (config.wg_private_key || '').trim()
  const pub = (config.server_public_key || '').trim()
  if (!priv || !pub) return null
  const addr = (config.wg_address || config.assigned_ip || '').trim()
  if (!addr) return null
  const dns = config.wg_dns || config.dns || '77.88.8.8,77.88.8.1'
  return `[Interface]
PrivateKey = ${priv}
Address = ${addr}
DNS = ${dns}
MTU = 1280

[Peer]
PublicKey = ${pub}
Endpoint = 127.0.0.1:${listenPort}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
`
}

/** Windows WireGuard tunnel падает (exit 10), если маршрутов слишком много. */
const MAX_WINDOWS_ALLOWED_ROUTES = 32

function countAllowedRoutes(allowedIPsValue) {
  return allowedIPsValue.split(',').map(s => s.trim()).filter(Boolean).length
}

function buildAllowedIPsForWindows(excludeIPs, send) {
  if (!excludeIPs.length) return '0.0.0.0/0'
  const split = generateExclusionAllowedIPs(excludeIPs)
  const n = countAllowedRoutes(split)
  if (n > MAX_WINDOWS_ALLOWED_ROUTES) {
    send?.(`[WG] Слишком много маршрутов (${n}) — используем AllowedIPs = 0.0.0.0/0`)
    return '0.0.0.0/0'
  }
  return split
}

function generateExclusionAllowedIPs(excludeIPs) {
  const ipToNum = ip => ip.split('.').reduce((a, b) => (a << 8 | Number(b)) >>> 0, 0)
  const numToIp = n => [(n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff].join('.')

  function cidrExclude(netNum, prefix, excludeNum) {
    const mask = prefix === 0 ? 0 : ((0xffffffff << (32 - prefix)) >>> 0)
    if ((excludeNum & mask) !== (netNum & mask)) return [[netNum, prefix]]
    if (prefix === 32) return []
    const np = prefix + 1
    const left = netNum
    const right = (netNum | (1 << (31 - prefix))) >>> 0
    const nm = ((0xffffffff << (32 - np)) >>> 0)
    if ((excludeNum & nm) === (left & nm)) return [...cidrExclude(left, np, excludeNum), [right, np]]
    return [[left, np], ...cidrExclude(right, np, excludeNum)]
  }

  let networks = [[0, 0]]
  for (const ip of excludeIPs) {
    networks = networks.flatMap(([net, pfx]) => cidrExclude(net, pfx, ipToNum(ip)))
  }
  return networks.map(([n, p]) => `${numToIp(n)}/${p}`).join(', ')
}

function installTunnelElevated(wgExe, stableConf, runtimeDir, send) {
  return new Promise((resolve) => {
    const logPath = path.join(STABLE_CONF_DIR, 'wg-install.log')
    const scriptPath = path.join(STABLE_CONF_DIR, 'wg-install.ps1')
    fs.mkdirSync(STABLE_CONF_DIR, { recursive: true })

    const ps1 = `
$log = '${logPath.replace(/'/g, "''")}'
function Log($m) { Add-Content -Path $log -Value $m -Encoding UTF8 }
Log "=== WG install $(Get-Date -Format o) ==="
try {
  & '${wgExe.replace(/'/g, "''")}' /uninstalltunnelservice ${TUNNEL_NAME} 2>&1 | ForEach-Object { Log $_ }
  $out = & '${wgExe.replace(/'/g, "''")}' /installtunnelservice '${stableConf.replace(/'/g, "''")}' 2>&1
  $out | ForEach-Object { Log $_ }
  if ($LASTEXITCODE -ne 0) { Log "install exit=$LASTEXITCODE"; exit $LASTEXITCODE }
  sc.exe start '${SERVICE_NAME}' 2>&1 | ForEach-Object { Log $_ }
  Log "OK"
  exit 0
} catch {
  Log "ERROR: $_"
  exit 1
}
`
    fs.writeFileSync(scriptPath, ps1, 'utf8')
    send('[WG] Запрос UAC — нажмите «Да» для установки WireGuard...')

    const launcher = spawn('powershell.exe', [
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
      `Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','${scriptPath.replace(/'/g, "''")}'`,
    ], { windowsHide: false })

    launcher.on('close', async (code) => {
      if (fs.existsSync(logPath)) {
        const log = fs.readFileSync(logPath, 'utf8').trim()
        log.split('\n').slice(-6).forEach(line => { if (line.trim()) send('[WG] ' + line.trim()) })
      }
      if (code !== 0) {
        send('[WG] UAC отменён или установка не удалась')
        resolve(false)
        return
      }
      const up = await waitForTunnelUp(35000, send)
      if (up) polishWgNetworkProfile(send)
      resolve(up)
    })

    launcher.on('error', () => {
      send('[WG] Не удалось запустить UAC')
      resolve(false)
    })
  })
}

async function applyWireGuardConfig(confPath, isDev, dirname, send, excludeIPs = [], options = {}) {
  const skipWdttWait = options.skipWdttWait === true
  const runtimeDir = prepareRuntimeDir(isDev, dirname, send)
  if (!runtimeDir) {
    send('[WG] Нет wireguard.exe / wintun.dll — переустановите Silent VPN')
    return false
  }

  const wgExe = path.join(runtimeDir, 'wireguard.exe')
  send(`[WG] wireguard.exe: ${wgExe}`)

  if (fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      const allowed = buildAllowedIPsForWindows(excludeIPs, send)
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${allowed}`)
      fs.writeFileSync(confPath, conf)
      fs.copyFileSync(confPath, path.join(STABLE_CONF_DIR, TUNNEL_CONF_NAME))
    } catch (e) {
      send('[WG] AllowedIPs: ' + e.message)
    }
  }

  if (!skipWdttWait) {
    send('[WG] Ожидание WDTT...')
    await waitForPort('127.0.0.1', 9000, 8000)
  } else {
    send('[WG] WDTT активен, поднимаем WireGuard...')
  }

  forceStopWireGuard(isDev, dirname, () => {})
  await sleep(1000)

  const stableConf = copyStableConf(confPath)
  send(`[WG] Конфиг: ${stableConf}`)

  if (!isProcessElevated()) {
    const ok = await installTunnelElevated(wgExe, stableConf, runtimeDir, send)
    if (ok) {
      send('[WG] Туннель активен')
      try {
        const wgCli = path.join(runtimeDir, 'wg.exe')
        if (fs.existsSync(wgCli)) {
          const st = execFileSync(wgCli, ['show', TUNNEL_NAME], { encoding: 'utf8', windowsHide: true })
          st.split('\n').filter(l => l.trim()).slice(0, 5).forEach(l => send('[WG] ' + l.trim()))
        }
      } catch {}
    } else {
      send('[WG] Запустите приложение через «Silent VPN (Admin).bat» или разрешите UAC')
    }
    return ok
  }

  runWgInstall(wgExe, stableConf, runtimeDir, send)

  if (await waitForTunnelUp(60000, send)) {
    polishWgNetworkProfile(send)
    send('[WG] Туннель активен')
    return true
  }

  logServiceState(send)
  try {
    const evt = execSync(
      `powershell.exe -NoProfile -Command "Get-WinEvent -LogName Application -MaxEvents 30 | Where-Object { $_.ProviderName -match 'WireGuard' } | Select-Object -First 3 -ExpandProperty Message"`,
      { encoding: 'utf8', windowsHide: true, timeout: 8000 },
    )
    if (evt.trim()) send('[WG] Event log: ' + evt.trim().slice(0, 300))
  } catch { /* ignore */ }

  send('[WG] Служба не поднялась — services.msc → WireGuardTunnel$wg-turn')
  return false
}

module.exports = {
  TUNNEL_CONF_NAME,
  TUNNEL_NAME,
  isProcessElevated,
  waitForPort,
  waitForWdttProxy,
  isUdpPortListening,
  waitForTunnelDown,
  isTunnelUp,
  isServiceRunning,
  resetWireGuardState: () => {},
  forceStopWireGuard,
  stopWireGuardTunnel,
  buildWgConfigFromApi,
  applyWireGuardConfig,
}
