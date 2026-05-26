/** Bundled WireGuard CLI — без установки приложения WireGuard из Program Files. */
const path = require('path')
const fs = require('fs')
const { spawn, execSync } = require('child_process')

const TUNNEL_NAME = 'silent-wg'

function resourcesDir(isDev, dirname) {
  return isDev ? path.join(dirname, '../../resources') : process.resourcesPath
}

function findBundledWireGuard(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    path.join(base, 'wireguard', 'wireguard.exe'),
    path.join(base, 'wireguard.exe'),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return null
}

function stopWireGuardTunnel(isDev, dirname) {
  const wgExe = findBundledWireGuard(isDev, dirname)
  if (wgExe) {
    try {
      execSync(`"${wgExe}" /uninstalltunnelservice ${TUNNEL_NAME}`, { windowsHide: true, stdio: 'ignore' })
    } catch {}
  }
  const serviceName = `WireGuardTunnel$${TUNNEL_NAME}`
  try {
    execSync(`sc stop "${serviceName}"`, { windowsHide: true, stdio: 'ignore' })
  } catch {}
  try {
    execSync(`sc delete "${serviceName}"`, { windowsHide: true, stdio: 'ignore' })
  } catch {}
  try {
    execSync('taskkill /F /IM wireguard.exe /T', { windowsHide: true, stdio: 'ignore' })
  } catch {}
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
    const nm = ((0xffffffff << (32 - np)) >>> 0)
    const left = netNum
    const right = (netNum | (1 << (31 - prefix))) >>> 0
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

async function applyWireGuardConfig(confPath, isDev, dirname, send, excludeIPs = []) {
  const wgExe = findBundledWireGuard(isDev, dirname)
  if (!wgExe) {
    send('[WG] ❌ wireguard.exe не найден в resources/wireguard/')
    return false
  }

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
  await new Promise(r => setTimeout(r, 800))

  return new Promise((resolve) => {
    send('[WG] Запуск туннеля (bundled CLI)...')
    const proc = spawn(wgExe, ['/installtunnelservice', confPath], { windowsHide: true })
    proc.on('close', (code) => {
      if (code === 0) {
        send('[WG] ✅ Туннель активен')
        resolve(true)
      } else {
        send(`[WG] ⚠ Ошибка (код ${code}). Запустите от администратора.`)
        resolve(false)
      }
    })
  })
}

module.exports = {
  TUNNEL_NAME,
  findBundledWireGuard,
  stopWireGuardTunnel,
  buildWgConfigFromApi,
  applyWireGuardConfig,
}
