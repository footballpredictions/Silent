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

/** Копируем wireguard.exe + wintun.dll в ProgramData — служба Windows не должна ссылаться на %TEMP%. */
function prepareRuntimeDir(isDev, dirname) {
  const bundled = findBundledDir(isDev, dirname)
  if (!bundled) return null
  const wintunSrc = path.join(bundled, 'wintun.dll')
  if (!fs.existsSync(wintunSrc)) return null

  const systemWg = path.join('C:\\Program Files\\WireGuard', 'wireguard.exe')
  const srcDir = fs.existsSync(systemWg) ? 'C:\\Program Files\\WireGuard' : bundled

  fs.mkdirSync(STABLE_WG_DIR, { recursive: true })
  for (const name of ['wireguard.exe', 'wg.exe']) {
    const src = path.join(srcDir, name)
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, path.join(STABLE_WG_DIR, name))
    }
  }
  fs.copyFileSync(wintunSrc, path.join(STABLE_WG_DIR, 'wintun.dll'))
  lastRuntimeDir = STABLE_WG_DIR
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
    const msg = (e.stdout || e.stderr || '').toString().trim()
    if (msg) send('[WG] sc start: ' + msg.slice(0, 200))
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

function isServiceRunning() {
  try {
    const out = execSync(`sc query "${SERVICE_NAME}"`, { encoding: 'utf8', windowsHide: true })
    return out.includes('RUNNING')
  } catch {
    return false
  }
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

function waitForPort(host, port, timeoutMs = 8000) {
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

  const runtimeDir = lastRuntimeDir || prepareRuntimeDir(isDev, dirname) || STABLE_WG_DIR
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
      resolve(await waitForTunnelUp(35000, send))
    })

    launcher.on('error', () => {
      send('[WG] Не удалось запустить UAC')
      resolve(false)
    })
  })
}

async function applyWireGuardConfig(confPath, isDev, dirname, send, excludeIPs = [], options = {}) {
  const skipWdttWait = options.skipWdttWait === true
  const runtimeDir = prepareRuntimeDir(isDev, dirname)
  if (!runtimeDir) {
    send('[WG] Нет wireguard.exe / wintun.dll — переустановите Silent VPN')
    return false
  }

  const wgExe = path.join(runtimeDir, 'wireguard.exe')
  send(`[WG] wireguard.exe: ${wgExe}`)

  if (excludeIPs.length > 0 && fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${generateExclusionAllowedIPs(excludeIPs)}`)
      fs.writeFileSync(confPath, conf)
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

  if (await waitForTunnelUp(35000, send)) {
    send('[WG] Туннель активен')
    return true
  }

  send('[WG] Служба не поднялась — services.msc → WireGuardTunnel$wg-turn')
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
