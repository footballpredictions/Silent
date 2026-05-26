/**
 * WireGuard Windows: /installtunnelservice (как задумано WireGuard), не прямой /tunnelservice.
 * wintun.dll + wireguard.exe bundled. Остановка: /uninstalltunnelservice.
 */
const path = require('path')
const fs = require('fs')
const os = require('os')
const net = require('net')
const { execSync } = require('child_process')

const TUNNEL_NAME = 'wg-turn'
const TUNNEL_CONF_NAME = 'wg-turn.conf'
const SERVICE_NAME = `WireGuardTunnel$${TUNNEL_NAME}`
const SYSTEM_WG_DIR = 'C:\\Program Files\\WireGuard'
const STABLE_CONF_DIR = path.join(process.env.ProgramData || 'C:\\ProgramData', 'SilentVPN')

let lastRuntimeDir = null

function resourcesDir(isDev, dirname) {
  return isDev ? path.join(dirname, '../../resources') : process.resourcesPath
}

function findBundledDir(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  for (const dir of [path.join(base, 'wireguard'), base]) {
    if (fs.existsSync(path.join(dir, 'wireguard.exe'))) return dir
  }
  return null
}

function isProcessElevated() {
  try {
    execSync('net session', { stdio: 'ignore', windowsHide: true })
    return true
  } catch {
    return false
  }
}

function prepareRuntimeDir(isDev, dirname) {
  const bundled = findBundledDir(isDev, dirname)
  if (!bundled) return null
  const wintunSrc = path.join(bundled, 'wintun.dll')
  if (!fs.existsSync(wintunSrc)) return null

  const srcDir = fs.existsSync(path.join(SYSTEM_WG_DIR, 'wireguard.exe')) ? SYSTEM_WG_DIR : bundled
  const runtimeDir = path.join(os.tmpdir(), 'silent-vpn-wg')
  fs.mkdirSync(runtimeDir, { recursive: true })

  for (const name of ['wireguard.exe', 'wg.exe']) {
    const src = path.join(srcDir, name)
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, path.join(runtimeDir, name))
    }
  }
  fs.copyFileSync(wintunSrc, path.join(runtimeDir, 'wintun.dll'))
  lastRuntimeDir = runtimeDir
  return runtimeDir
}

function runCmd(cmd, cwd) {
  try {
    return execSync(cmd, { cwd, encoding: 'utf8', windowsHide: true, timeout: 30000, stdio: 'pipe' })
  } catch (e) {
    const out = (e.stdout || e.stderr || e.message || '').toString().trim()
    return out || null
  }
}

function psExec(script) {
  const file = path.join(os.tmpdir(), `silent-wg-${Date.now()}.ps1`)
  try {
    fs.writeFileSync(file, script, 'utf8')
    execSync(`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${file}"`, {
      windowsHide: true,
      stdio: 'ignore',
      timeout: 25000,
    })
  } catch {} finally {
    try { fs.unlinkSync(file) } catch {}
  }
}

function isTunnelUp() {
  try {
    const out = execSync(
      'powershell.exe -NoProfile -Command "Get-NetAdapter -EA SilentlyContinue | ? { ($_.Name -eq \'wg-turn\' -or $_.InterfaceDescription -match \'WireGuard Tunnel\') -and $_.Status -eq \'Up\' } | Select -First 1 -Expand Name"',
      { windowsHide: true, encoding: 'utf8', timeout: 8000 },
    )
    return !!out.trim()
  } catch {
    return false
  }
}

function isServiceRunning() {
  try {
    const out = execSync(`sc query "${SERVICE_NAME}"`, { encoding: 'utf8', windowsHide: true })
    return out.includes('RUNNING')
  } catch {
    return false
  }
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

async function waitForTunnelUp(maxMs = 15000) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    if (isTunnelUp() || isServiceRunning()) return true
    await sleep(500)
  }
  return isTunnelUp() || isServiceRunning()
}

function waitForPort(host, port, timeoutMs = 45000) {
  return new Promise((resolve) => {
    const start = Date.now()
    const probe = () => {
      const sock = net.createConnection({ host, port, timeout: 2000 }, () => {
        sock.destroy()
        resolve(true)
      })
      sock.on('error', () => {
        if (Date.now() - start >= timeoutMs) resolve(false)
        else setTimeout(probe, 400)
      })
      sock.on('timeout', () => {
        sock.destroy()
        if (Date.now() - start >= timeoutMs) resolve(false)
        else setTimeout(probe, 400)
      })
    }
    probe()
  })
}

function copyStableConf(confPath) {
  fs.mkdirSync(STABLE_CONF_DIR, { recursive: true })
  const stable = path.join(STABLE_CONF_DIR, TUNNEL_CONF_NAME)
  fs.copyFileSync(confPath, stable)
  return stable
}

function forceStopWireGuard(isDev, dirname, send) {
  send?.('[WG] Остановка туннеля...')

  const runtimeDir = lastRuntimeDir || prepareRuntimeDir(isDev, dirname) || path.join(os.tmpdir(), 'silent-vpn-wg')
  const wgExe = path.join(runtimeDir, 'wireguard.exe')

  if (fs.existsSync(wgExe)) {
    runCmd(`"${wgExe}" /uninstalltunnelservice ${TUNNEL_NAME}`, runtimeDir)
  }

  try { execSync(`sc stop "${SERVICE_NAME}"`, { windowsHide: true, stdio: 'ignore' }) } catch {}
  try { execSync(`sc delete "${SERVICE_NAME}"`, { windowsHide: true, stdio: 'ignore' }) } catch {}

  psExec(`
    Get-CimInstance Win32_Process -Filter "Name='wireguard.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -match 'wg-turn|SilentVPN|silent-vpn-wg' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  `)

  psExec(`
    Get-NetAdapter -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -eq 'wg-turn' -or $_.InterfaceDescription -match 'WireGuard Tunnel.*wg-turn' } |
      ForEach-Object {
        Disable-NetAdapter -Name $_.Name -Confirm:$false -ErrorAction SilentlyContinue
      }
  `)

  psExec('ipconfig /flushdns')
  send?.('[WG] Туннель остановлен')
}

function stopWireGuardTunnel(isDev, dirname, send) {
  forceStopWireGuard(isDev, dirname, send)
}

function buildWgConfigFromApi(config, listenPort = 9000) {
  const priv = (config.wg_private_key || '').trim()
  const pub = (config.server_public_key || '').trim()
  if (!priv || !pub) return null
  const dns = config.wg_dns || '77.88.8.8,77.88.8.1'
  return `[Interface]
PrivateKey = ${priv}
Address = ${config.wg_address}
DNS = ${dns}

[Peer]
PublicKey = ${pub}
Endpoint = 127.0.0.1:${listenPort}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
`
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

async function applyWireGuardConfig(confPath, isDev, dirname, send, excludeIPs = []) {
  const runtimeDir = prepareRuntimeDir(isDev, dirname)
  if (!runtimeDir) {
    send('[WG] Нет wireguard.exe / wintun.dll в resources/wireguard/')
    return false
  }

  const wgExe = path.join(runtimeDir, 'wireguard.exe')

  if (excludeIPs.length > 0 && fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${generateExclusionAllowedIPs(excludeIPs)}`)
      fs.writeFileSync(confPath, conf)
    } catch (e) {
      send('[WG] AllowedIPs: ' + e.message)
    }
  }

  send('[WG] Ожидание WDTT (127.0.0.1:9000)...')
  const wdttReady = await waitForPort('127.0.0.1', 9000, 50000)
  if (!wdttReady) {
    send('[WG] WDTT не слушает порт 9000')
    return false
  }

  forceStopWireGuard(isDev, dirname, () => {})
  await new Promise(r => setTimeout(r, 800))

  const stableConf = copyStableConf(confPath)
  send(`[WG] Конфиг: ${stableConf}`)

  if (!isProcessElevated()) {
    send('[WG] Нужны права администратора для WireGuard')
    return false
  }

  send('[WG] Установка туннеля (WireGuardTunnel$wg-turn)...')
  runCmd(`"${wgExe}" /uninstalltunnelservice ${TUNNEL_NAME}`, runtimeDir)
  const installOut = runCmd(`"${wgExe}" /installtunnelservice "${stableConf}"`, runtimeDir)
  if (installOut) send('[WG] ' + installOut.slice(0, 200))

  try { execSync(`sc start "${SERVICE_NAME}"`, { windowsHide: true, stdio: 'ignore', timeout: 15000 }) } catch {}

  if (await waitForTunnelUp(20000)) {
    send('[WG] Туннель активен')
    return true
  }

  send('[WG] Служба не поднялась. Проверьте WireGuard в services.msc')
  return false
}

module.exports = {
  TUNNEL_CONF_NAME,
  TUNNEL_NAME,
  isProcessElevated,
  waitForPort,
  resetWireGuardState: () => {},
  forceStopWireGuard,
  stopWireGuardTunnel,
  buildWgConfigFromApi,
  applyWireGuardConfig,
}
