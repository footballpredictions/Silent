/** WireGuard: один запуск за подключение, без циклов UAC и taskkill. */
const path = require('path')
const fs = require('fs')
const os = require('os')
const { spawn, execSync } = require('child_process')

const TUNNEL_CONF_NAME = 'wg-turn.conf'
const SYSTEM_WG_DIR = 'C:\\Program Files\\WireGuard'

let wgProcess = null
let wgApplyLocked = false

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
  if (wgProcess) {
    try { wgProcess.kill() } catch {}
    wgProcess = null
  }
}

function prepareRuntimeDir(isDev, dirname, send) {
  const bundled = findBundledDir(isDev, dirname)
  if (!bundled) {
    send('[WG] wireguard.exe не найден в resources/wireguard/')
    return null
  }
  const wintunSrc = path.join(bundled, 'wintun.dll')
  if (!fs.existsSync(wintunSrc)) {
    send('[WG] wintun.dll не найден — пересоберите приложение')
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

function stopWireGuardTunnel() {
  resetWireGuardState()
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
      'powershell.exe -NoProfile -Command "Get-NetAdapter -EA SilentlyContinue | ? { $_.InterfaceDescription -match \'WireGuard|Wintun\' -and $_.Status -eq \'Up\' } | Select -First 1 -Expand Name"',
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

  const runtimeDir = prepareRuntimeDir(isDev, dirname, send)
  if (!runtimeDir) return false

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

  if (wgProcess) {
    try { wgProcess.kill() } catch {}
    wgProcess = null
    await new Promise(r => setTimeout(r, 400))
  }

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
  resetWireGuardState,
  stopWireGuardTunnel,
  buildWgConfigFromApi,
  applyWireGuardConfig,
}
