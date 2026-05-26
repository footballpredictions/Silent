/** WireGuard через bundled wireguard.exe + wintun.dll — без installtunnelservice / установки службы. */
const path = require('path')
const fs = require('fs')
const { spawn, execSync } = require('child_process')

const TUNNEL_CONF_NAME = 'wg-turn.conf'
let wgProcess = null

function resourcesDir(isDev, dirname) {
  return isDev ? path.join(dirname, '../../resources') : process.resourcesPath
}

function findWireGuardDir(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    path.join(base, 'wireguard'),
    base,
  ]
  for (const dir of candidates) {
    const wgExe = path.join(dir, 'wireguard.exe')
    if (fs.existsSync(wgExe)) return dir
  }
  return null
}

function getBinaries(isDev, dirname, send) {
  const dir = findWireGuardDir(isDev, dirname)
  if (!dir) {
    send('[WG] ❌ wireguard.exe не найден в resources/wireguard/')
    return null
  }
  const wgExe = path.join(dir, 'wireguard.exe')
  const wintun = path.join(dir, 'wintun.dll')
  if (!fs.existsSync(wintun)) {
    send('[WG] ❌ wintun.dll не найден рядом с wireguard.exe')
    return null
  }
  return { dir, wgExe, wintun }
}

function cleanupLegacyService() {
  const serviceName = 'WireGuardTunnel$wg-turn'
  try { execSync(`sc stop "${serviceName}"`, { windowsHide: true, stdio: 'ignore' }) } catch {}
  try { execSync(`sc delete "${serviceName}"`, { windowsHide: true, stdio: 'ignore' }) } catch {}
  try { execSync(`sc stop "WireGuardTunnel$silent-wg"`, { windowsHide: true, stdio: 'ignore' }) } catch {}
  try { execSync(`sc delete "WireGuardTunnel$silent-wg"`, { windowsHide: true, stdio: 'ignore' }) } catch {}
}

function stopWireGuardTunnel(isDev, dirname) {
  if (wgProcess) {
    try { wgProcess.kill() } catch {}
    wgProcess = null
  }
  try {
    execSync('taskkill /F /IM wireguard.exe /T', { windowsHide: true, stdio: 'ignore' })
  } catch {}
  cleanupLegacyService()
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
    const excl = ipToNum(ip)
    networks = networks.flatMap(([net, pfx]) => cidrExclude(net, pfx, excl))
  }
  return networks.map(([n, p]) => `${numToIp(n)}/${p}`).join(', ')
}

function isWintunAdapterUp() {
  try {
    const out = execSync(
      'powershell.exe -NoProfile -Command "Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceDescription -match \'WireGuard|Wintun\' -and $_.Status -eq \'Up\' } | Select-Object -First 1 -ExpandProperty Name"',
      { windowsHide: true, encoding: 'utf8', timeout: 8000 },
    )
    return !!out.trim()
  } catch {
    return false
  }
}

function runTunnelForeground(wgExe, confPath, cwd) {
  return new Promise((resolve) => {
    try {
      wgProcess = spawn(wgExe, ['/tunnelservice', confPath], {
        cwd,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
      })
    } catch {
      resolve(false)
      return
    }

    let settled = false
    const finish = (ok) => {
      if (settled) return
      settled = true
      resolve(ok)
    }

    wgProcess.on('error', () => finish(false))
    wgProcess.on('close', () => {
      if (wgProcess && wgProcess.exitCode !== null) wgProcess = null
      if (!settled) finish(false)
    })

    wgProcess.stderr?.on('data', () => {})
    wgProcess.stdout?.on('data', () => {})

    setTimeout(() => {
      if (!wgProcess || wgProcess.killed) {
        finish(false)
        return
      }
      if (isWintunAdapterUp()) {
        finish(true)
        return
      }
      // процесс жив — считаем успехом (адаптер может подняться чуть позже)
      finish(true)
    }, 2500)
  })
}

function runTunnelElevated(wgExe, confPath, cwd) {
  return new Promise((resolve) => {
    const ps = [
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
      `$ErrorActionPreference='SilentlyContinue'; `
      + `$wg=${JSON.stringify(wgExe)}; $cfg=${JSON.stringify(confPath)}; $dir=${JSON.stringify(cwd)}; `
      + `Start-Process -FilePath $wg -ArgumentList '/tunnelservice',$cfg -WorkingDirectory $dir -WindowStyle Hidden -Verb RunAs; `
      + `Start-Sleep -Seconds 4; `
      + `$a=Get-NetAdapter | Where-Object { $_.InterfaceDescription -match 'WireGuard|Wintun' -and $_.Status -eq 'Up' } | Select-Object -First 1; `
      + `if ($a) { exit 0 } else { exit 1 }`,
    ]
    const proc = spawn('powershell.exe', ps, { windowsHide: true })
    proc.on('close', code => resolve(code === 0))
    proc.on('error', () => resolve(false))
  })
}

async function applyWireGuardConfig(confPath, isDev, dirname, send, excludeIPs = []) {
  const bins = getBinaries(isDev, dirname, send)
  if (!bins) return false
  const { dir, wgExe } = bins

  if (excludeIPs.length > 0 && fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${generateExclusionAllowedIPs(excludeIPs)}`)
      fs.writeFileSync(confPath, conf)
    } catch (e) {
      send('[WG] AllowedIPs patch: ' + e.message)
    }
  }

  stopWireGuardTunnel(isDev, dirname)
  await new Promise(r => setTimeout(r, 600))

  send('[WG] Запуск туннеля (wintun)...')
  let ok = await runTunnelForeground(wgExe, confPath, dir)
  if (!ok) {
    send('[WG] Нужны права администратора для Wintun (один раз)...')
    ok = await runTunnelElevated(wgExe, confPath, dir)
  }

  if (ok) {
    send('[WG] ✅ Туннель активен')
    return true
  }

  send('[WG] ⚠ Не удалось поднять туннель. Разрешите UAC или переустановите приложение.')
  return false
}

module.exports = {
  TUNNEL_CONF_NAME,
  findWireGuardDir,
  stopWireGuardTunnel,
  buildWgConfigFromApi,
  applyWireGuardConfig,
}
