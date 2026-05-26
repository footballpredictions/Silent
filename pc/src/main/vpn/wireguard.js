/**
 * WireGuard на Windows — bundled wireguard.exe + wintun.dll (аналог GoBackend на Android).
 * Жизненный цикл туннеля привязан к Silent VPN: при disconnect/quit — полная остановка.
 */
const path = require('path')
const fs = require('fs')
const os = require('os')
const { spawn, execSync } = require('child_process')

const TUNNEL_NAME = 'wg-turn'
const TUNNEL_CONF_NAME = 'wg-turn.conf'
const SYSTEM_WG_DIR = 'C:\\Program Files\\WireGuard'

let wgProcess = null
let wgApplyLocked = false
let lastConfPath = null
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

function resetWireGuardState() {
  wgApplyLocked = false
}

function prepareRuntimeDir(isDev, dirname, send) {
  const bundled = findBundledDir(isDev, dirname)
  if (!bundled) {
    send?.('[WG] wireguard.exe не найден в resources/wireguard/')
    return null
  }
  const wintunSrc = path.join(bundled, 'wintun.dll')
  if (!fs.existsSync(wintunSrc)) {
    send?.('[WG] wintun.dll не найден — пересоберите приложение')
    return null
  }

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
  return runtimeDir
}

function psExec(script) {
  const file = path.join(os.tmpdir(), `silent-wg-cleanup-${Date.now()}.ps1`)
  try {
    fs.writeFileSync(file, script, 'utf8')
    execSync(`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${file}"`, {
      windowsHide: true,
      stdio: 'ignore',
      timeout: 20000,
    })
  } catch {} finally {
    try { fs.unlinkSync(file) } catch {}
  }
}

/** Остановить только наши процессы/адаптеры Silent VPN (не трогаем чужой WireGuard). */
function forceStopWireGuard(isDev, dirname, send) {
  send?.('[WG] Остановка туннеля...')

  if (wgProcess?.pid) {
    try {
      execSync(`taskkill /PID ${wgProcess.pid} /T /F`, { windowsHide: true, stdio: 'ignore' })
    } catch {}
    wgProcess = null
  }

  const runtimeDir = lastRuntimeDir || path.join(os.tmpdir(), 'silent-vpn-wg')
  const wgExe = path.join(runtimeDir, 'wireguard.exe')
  const conf = lastConfPath || path.join(os.tmpdir(), TUNNEL_CONF_NAME)

  if (fs.existsSync(wgExe)) {
    try {
      execSync(`"${wgExe}" /uninstalltunnelservice ${TUNNEL_NAME}`, { windowsHide: true, stdio: 'ignore' })
    } catch {}
    if (fs.existsSync(conf)) {
      try {
        execSync(`"${wgExe}" /uninstalltunnelservice "${conf}"`, { windowsHide: true, stdio: 'ignore' })
      } catch {}
    }
  }

  for (const svc of [`WireGuardTunnel$${TUNNEL_NAME}`, 'WireGuardTunnel$silent-wg']) {
    try { execSync(`sc stop "${svc}"`, { windowsHide: true, stdio: 'ignore' }) } catch {}
    try { execSync(`sc delete "${svc}"`, { windowsHide: true, stdio: 'ignore' }) } catch {}
  }

  psExec(`
    $markers = @('wg-turn.conf','silent-vpn-wg','${TUNNEL_NAME.replace(/'/g, "''")}')
    Get-CimInstance Win32_Process -Filter "Name='wireguard.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $cmd = $_.CommandLine; $markers | Where-Object { $cmd -like "*$_*" } } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  `)

  psExec(`
    Get-NetAdapter -ErrorAction SilentlyContinue |
      Where-Object {
        $_.Name -eq '${TUNNEL_NAME}' -or
        $_.InterfaceDescription -match 'WireGuard Tunnel.*wg-turn|Wintun.*wg-turn'
      } |
      ForEach-Object {
        Disable-NetAdapter -Name $_.Name -Confirm:$false -ErrorAction SilentlyContinue
        Remove-NetAdapter -Name $_.Name -Confirm:$false -ErrorAction SilentlyContinue
      }
  `)

  psExec('ipconfig /flushdns')
  resetWireGuardState()
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

function isTunnelUp() {
  try {
    const out = execSync(
      'powershell.exe -NoProfile -Command "Get-NetAdapter -EA SilentlyContinue | ? { ($_.Name -eq \'wg-turn\' -or $_.InterfaceDescription -match \'WireGuard|Wintun\') -and $_.Status -eq \'Up\' } | Select -First 1 -Expand Name"',
      { windowsHide: true, encoding: 'utf8', timeout: 5000 },
    )
    return !!out.trim()
  } catch {
    return false
  }
}

function runTunnelOnce(wgExe, confPath, cwd) {
  return new Promise((resolve) => {
    let settled = false
    const finish = (ok) => {
      if (settled) return
      settled = true
      resolve(ok)
    }

    try {
      wgProcess = spawn(wgExe, ['/tunnelservice', confPath], {
        cwd,
        windowsHide: true,
        stdio: 'ignore',
        detached: false,
      })
    } catch {
      finish(false)
      return
    }

    wgProcess.on('error', () => finish(false))
    wgProcess.on('exit', () => {
      wgProcess = null
      if (!settled) finish(false)
    })

    setTimeout(() => {
      if (wgProcess && !wgProcess.killed) {
        finish(isTunnelUp() || true)
      } else {
        finish(false)
      }
    }, 3000)
  })
}

async function applyWireGuardConfig(confPath, isDev, dirname, send, excludeIPs = []) {
  if (wgApplyLocked) {
    send('[WG] Уже пробовали поднять туннель в этой сессии')
    return false
  }
  wgApplyLocked = true
  lastConfPath = confPath

  const runtimeDir = prepareRuntimeDir(isDev, dirname, send)
  if (!runtimeDir) return false
  lastRuntimeDir = runtimeDir

  const wgExe = path.join(runtimeDir, 'wireguard.exe')
  if (!fs.existsSync(wgExe)) {
    send('[WG] wireguard.exe недоступен')
    return false
  }

  if (excludeIPs.length > 0 && fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${generateExclusionAllowedIPs(excludeIPs)}`)
      fs.writeFileSync(confPath, conf)
    } catch (e) {
      send('[WG] AllowedIPs: ' + e.message)
    }
  }

  forceStopWireGuard(isDev, dirname, () => {})
  await new Promise(r => setTimeout(r, 500))

  send('[WG] Запуск туннеля...')
  const ok = await runTunnelOnce(wgExe, confPath, runtimeDir)

  if (ok) {
    send('[WG] Туннель активен')
    return true
  }

  send('[WG] Не удалось поднять туннель')
  return false
}

module.exports = {
  TUNNEL_CONF_NAME,
  TUNNEL_NAME,
  resetWireGuardState,
  forceStopWireGuard,
  stopWireGuardTunnel,
  buildWgConfigFromApi,
  applyWireGuardConfig,
}
