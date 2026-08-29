/**
 * WireGuard Linux — тот же контракт, что Windows `wireguard.js`.
 * Туннель wg-turn, AllowedIPs как на PC (0.0.0.0/1 + 128.0.0.0/1, bootstrap 10.66.66.0/24),
 * bypass /32 через физический шлюз. Права: pkexec (аналог UAC).
 */
const path = require('path')
const fs = require('fs')
const os = require('os')
const { exec, execFile, execFileSync } = require('child_process')
const { promisify } = require('util')
const execAsync = promisify(exec)
const execFileAsync = promisify(execFile)

const TUNNEL_NAME = 'wg-turn'
const TUNNEL_CONF_NAME = 'wg-turn.conf'
const FALLBACK_BACKEND_IP = '132.243.234.162'
const WG_DNS = '1.1.1.1, 1.0.0.1, 77.88.8.8'
const STABLE_CONF_DIR = path.join(os.homedir(), '.local', 'share', 'SilentVPN')

function pickDnsServers(value) {
  return String(value || '')
    .split(/[,;\s]+/)
    .map(s => s.trim())
    .filter(Boolean)
    .join(', ')
}

function normalizeDnsValue(raw, override) {
  const fromOverride = pickDnsServers(override)
  if (fromOverride) return fromOverride
  const fromServer = pickDnsServers(raw)
  if (fromServer.split(/,\s*/).includes('10.66.66.1')) return fromServer
  return WG_DNS
}

let lastRuntimeDir = null
let savedPhysicalGateway = null
let wgStopChain = Promise.resolve()
let bypassChain = Promise.resolve()
let wgApplyEpoch = 0
let lastHelperPath = null
let lastWgGo = 'auto'

function beginWgApply() {
  wgApplyEpoch += 1
  return wgApplyEpoch
}

function currentWgApplyEpoch() {
  return wgApplyEpoch
}

function confCryptoIdentity(confText) {
  const text = String(confText || '')
  const priv = (text.match(/^\s*PrivateKey\s*=\s*(\S+)/m) || [])[1] || ''
  const pub = (text.match(/^\s*PublicKey\s*=\s*(\S+)/m) || [])[1] || ''
  if (!priv && !pub) return ''
  return `${priv}|${pub}`
}

function lastStableConfText() {
  try {
    const p = path.join(STABLE_CONF_DIR, TUNNEL_CONF_NAME)
    if (!fs.existsSync(p)) return ''
    return fs.readFileSync(p, 'utf8')
  } catch {
    return ''
  }
}

function enqueueWgStop(fn) {
  const next = wgStopChain.then(fn, fn)
  wgStopChain = next.catch(() => {})
  return next
}

function enqueueBypass(fn) {
  const next = bypassChain.then(fn, fn)
  bypassChain = next.catch(() => {})
  return next
}

function waitWgStopIdle() {
  return wgStopChain
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

function resourcesDir(isDev, dirname) {
  return isDev ? path.join(dirname, '../../resources') : process.resourcesPath
}

function findHelper(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    path.join(base, 'linux', 'silent-wg-helper'),
    path.join(base, 'silent-wg-helper'),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return null
}

function findWireguardGo(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    path.join(base, 'linux', 'wireguard-go'),
    path.join(base, 'wireguard-go'),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return 'auto'
}

function prepareRuntimeDir(isDev, dirname, send) {
  const helper = findHelper(isDev, dirname)
  if (!helper) {
    send?.('[WG] Нет silent-wg-helper — пересоберите Linux-клиент')
    return null
  }
  lastHelperPath = helper
  lastRuntimeDir = path.dirname(helper)
  try {
    fs.chmodSync(helper, 0o755)
  } catch { /* ignore */ }
  lastWgGo = findWireguardGo(isDev, dirname)
  if (lastWgGo && lastWgGo !== 'auto') {
    try { fs.chmodSync(lastWgGo, 0o755) } catch { /* ignore */ }
    send?.(`[WG] wireguard-go: ${lastWgGo}`)
  } else {
    send?.('[WG] wireguard-go не bundled — kernel WireGuard / PATH')
  }
  return lastRuntimeDir
}

function isProcessElevated() {
  try {
    return typeof process.getuid === 'function' && process.getuid() === 0
  } catch {
    return false
  }
}

function helperCmd(args, timeoutMs = 45000) {
  const helper = lastHelperPath
  if (!helper) {
    const err = new Error('silent-wg-helper not found')
    err.code = 'ENOHELPER'
    throw err
  }
  const elevated = isProcessElevated()
  const bin = elevated ? helper : 'pkexec'
  const binArgs = elevated ? args : [helper, ...args]
  return execFileAsync(bin, binArgs, {
    encoding: 'utf8',
    timeout: timeoutMs,
    maxBuffer: 2 * 1024 * 1024,
  })
}

async function helperOut(args, timeoutMs = 20000) {
  try {
    const { stdout, stderr } = await helperCmd(args, timeoutMs)
    return String(stdout || stderr || '').trim()
  } catch (e) {
    const out = [e.stdout, e.stderr, e.message].filter(Boolean).join('\n').trim()
    const err = new Error(out || e.message)
    err.code = e.code
    throw err
  }
}

function parseBypassTarget(raw) {
  const s = String(raw || '').trim()
  const m = s.match(/^(\d{1,3}(?:\.\d{1,3}){3})(?:\/(\d{1,2}))?$/)
  if (!m) return null
  const ip = m[1]
  const prefix = m[2] != null ? Number(m[2]) : 32
  if (prefix < 0 || prefix > 32) return null
  return { ip, prefix, dest: `${ip}/${prefix}` }
}

function buildAllowedIPsForLinux(excludeIPs, send) {
  void excludeIPs
  send?.('[WG] AllowedIPs = 0.0.0.0/1, 128.0.0.0/1 (full без kill-switch; API/VK bypass)')
  return '0.0.0.0/1, 128.0.0.0/1'
}

function normalizeWgConfText(conf) {
  const known = new Set([
    'PrivateKey', 'Address', 'DNS', 'MTU', 'PublicKey', 'Endpoint',
    'AllowedIPs', 'PersistentKeepalive', 'PresharedKey', 'ListenPort',
  ])
  return String(conf || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .split('\n')
    .map((line) => {
      const trimmed = line.trimEnd()
      const eq = trimmed.indexOf('=')
      if (eq <= 0) return trimmed
      const key = trimmed.slice(0, eq).trim()
      if (!known.has(key)) return trimmed
      const val = trimmed.slice(eq + 1).trim()
      const indent = line.match(/^(\s*)/)?.[1] || ''
      return `${indent}${key} = ${val}`
    })
    .join('\n')
}

function buildWgConfigFromApi(config, listenPort = 9000) {
  const priv = (config.wg_private_key || '').trim()
  const pub = (config.server_public_key || '').trim()
  if (!priv || !pub) return null
  const addr = (config.wg_address || config.assigned_ip || '').trim()
  if (!addr) return null
  const dns = normalizeDnsValue(config.wg_dns || config.dns, config.dns_override)
  return `[Interface]
PrivateKey = ${priv}
Address = ${addr}
DNS = ${dns}
MTU = 1200

[Peer]
PublicKey = ${pub}
Endpoint = 127.0.0.1:${listenPort}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
`
}

function copyStableConf(confPath) {
  fs.mkdirSync(STABLE_CONF_DIR, { recursive: true })
  const dest = path.join(STABLE_CONF_DIR, TUNNEL_CONF_NAME)
  fs.copyFileSync(confPath, dest)
  try { fs.chmodSync(dest, 0o600) } catch { /* ignore */ }
  return dest
}

async function isTunnelUpAsync() {
  try {
    const { stdout } = await execAsync(`ip -o link show ${TUNNEL_NAME}`, {
      encoding: 'utf8',
      timeout: 4000,
    })
    return /UP/i.test(String(stdout || ''))
  } catch {
    return false
  }
}

function isTunnelUp() {
  try {
    const out = execFileSync('ip', ['-o', 'link', 'show', TUNNEL_NAME], {
      encoding: 'utf8',
      timeout: 4000,
    })
    return /UP/i.test(String(out || ''))
  } catch {
    return false
  }
}

async function isServiceRunningAsync() {
  return isTunnelUpAsync()
}

function isServiceRunning() {
  return isTunnelUp()
}

async function isWgStillPresentAsync() {
  return isTunnelUpAsync()
}

async function capturePhysicalGateway(send) {
  const prev = savedPhysicalGateway
  try {
    const out = await helperOut(['gateway'], 12000)
    const parts = String(out || '').trim().split(/\s+/)
    if (parts.length >= 2 && /^\d+\.\d+\.\d+\.\d+$/.test(parts[0])) {
      savedPhysicalGateway = {
        nextHop: parts[0],
        ifIndex: 0,
        alias: parts[1],
      }
      send?.(`[WG] Шлюз до VPN: ${savedPhysicalGateway.nextHop} (${savedPhysicalGateway.alias})`)
      return savedPhysicalGateway
    }
  } catch (e) {
    // без pkexec — пробуем ip route от пользователя
    try {
      const { stdout } = await execAsync('ip -4 route show default', { encoding: 'utf8', timeout: 5000 })
      const m = String(stdout || '').match(/via\s+(\d+\.\d+\.\d+\.\d+).*dev\s+(\S+)/)
      if (m) {
        savedPhysicalGateway = { nextHop: m[1], ifIndex: 0, alias: m[2] }
        send?.(`[WG] Шлюз до VPN: ${m[1]} (${m[2]})`)
        return savedPhysicalGateway
      }
    } catch { /* ignore */ }
    send?.(`[WG] gateway: ${e?.message || e}`)
  }
  return prev?.nextHop ? prev : savedPhysicalGateway
}

async function addServerBypassRoutesUnlocked(excludeIPs, send, options = {}) {
  const targets = [...new Set(
    (excludeIPs || []).map(parseBypassTarget).filter(Boolean).map(t => t.dest),
  )]
  if (!targets.length) return false
  const quiet = options.quiet === true
  const label = String(options.label || 'API').trim() || 'API'
  if (!savedPhysicalGateway?.nextHop || !savedPhysicalGateway?.alias) {
    await capturePhysicalGateway(send)
  }
  if (!savedPhysicalGateway?.nextHop || !savedPhysicalGateway?.alias) {
    send?.(`[WG] Bypass ${label} не применён — нет шлюза`, 'W')
    return false
  }
  const chunkSize = 40
  let anyOk = false
  for (let i = 0; i < targets.length; i += chunkSize) {
    const chunk = targets.slice(i, i + chunkSize)
    try {
      await helperOut(
        ['bypass-add', savedPhysicalGateway.nextHop, savedPhysicalGateway.alias, ...chunk],
        Math.min(120000, 15000 + chunk.length * 200),
      )
      anyOk = true
    } catch (e) {
      send?.(`[WG] Bypass ${label} chunk ${Math.floor(i / chunkSize) + 1}: ${String(e.message || e).slice(0, 120)}`, 'W')
    }
  }
  if (!anyOk) {
    send?.(`[WG] Bypass ${label} не применён`, 'W')
    return false
  }
  if (!quiet) {
    const preview = targets.length <= 6 ? targets.join(', ') : `${targets.slice(0, 6).join(', ')}…(+${targets.length - 6})`
    send?.(`[WG] Bypass ${label}: ${preview} → ${savedPhysicalGateway.nextHop}`)
  }
  return true
}

async function addServerBypassRoutes(excludeIPs, send, options = {}) {
  return enqueueBypass(() => addServerBypassRoutesUnlocked(excludeIPs, send, options))
}

async function removeHostBypassRoutes(excludeIPs, send, epoch = null) {
  const targets = [...new Set(
    (excludeIPs || []).map(parseBypassTarget).filter(Boolean).map(t => t.dest),
  )]
  if (!targets.length) return
  if (epoch != null && epoch !== wgApplyEpoch) {
    send?.('[WG] Bypass host: снятие прервано — уже новый connect')
    return
  }
  try {
    await helperOut(['bypass-del', ...targets], 20000)
  } catch { /* ignore */ }
  if (epoch != null && epoch !== wgApplyEpoch) return
  send?.(`[WG] Bypass host routes сняты: ${targets.length}`)
}

async function applyWgDns(send, dnsValue = WG_DNS) {
  const servers = pickDnsServers(dnsValue)
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
  if (!servers.length) return
  try {
    await helperOut(['dns-set', TUNNEL_NAME, servers.join(',')], 12000)
    send?.(`[WG] DNS на адаптере: ${servers.join(', ')}`)
  } catch (e) {
    send?.(`[WG] DNS: ${e?.message || e}`, 'W')
  }
}

async function finalizeTunnelUp(send, excludeIPs, subnetOnly, dnsValue = WG_DNS) {
  if (!subnetOnly) {
    await applyWgDns(send, dnsValue)
  }
  if (excludeIPs.length) {
    await addServerBypassRoutes(excludeIPs, send)
  }
}

async function waitForTunnelUp(maxMs = 30000, send) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    if (await isTunnelUpAsync()) return true
    await sleep(250)
  }
  const up = await isTunnelUpAsync()
  if (!up) send?.('[WG] интерфейс wg-turn не поднялся')
  return up
}

async function waitForTunnelDown(maxMs = 15000, send) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    if (!(await isTunnelUpAsync())) return true
    await sleep(400)
  }
  const down = !(await isTunnelUpAsync())
  if (!down) send?.('[WG] Туннель ещё не остановлен полностью')
  return down
}

async function isUdpPortListening(port, host = '127.0.0.1') {
  const dgram = require('dgram')
  return new Promise((resolve) => {
    const s = dgram.createSocket('udp4')
    let settled = false
    const done = (v) => {
      if (settled) return
      settled = true
      try { s.close() } catch { /* ignore */ }
      resolve(v)
    }
    s.once('error', (e) => {
      done(/EADDRINUSE/i.test(String(e?.message || e)))
    })
    try {
      s.bind(port, host, () => done(false))
    } catch {
      done(false)
    }
    setTimeout(() => done(false), 400)
  })
}

async function waitForWdttProxy(host, port, timeoutMs = 60000, send, confPath = null) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await isUdpPortListening(port, host)) {
      send?.('[WG] WDTT: UDP прокси слушает ' + host + ':' + port)
      return true
    }
    if (confPath && fs.existsSync(confPath)) {
      try {
        const text = fs.readFileSync(confPath, 'utf8')
        if (text.includes('[Interface]') && text.includes(`127.0.0.1:${port}`)) {
          send?.('[WG] WDTT: конфиг wg-turn.conf готов')
          return true
        }
      } catch { /* ignore */ }
    }
    await sleep(50)
  }
  send?.('[WG] WDTT: таймаут ожидания UDP ' + host + ':' + port)
  return false
}

function waitForPort(host, port, timeoutMs = 8000) {
  return waitForWdttProxy(host, port, timeoutMs)
}

async function waitForUdpPortFree(host, port, timeoutMs = 8000, send) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (!(await isUdpPortListening(port, host))) return true
    await sleep(100)
  }
  send?.(`[WG] UDP ${host}:${port} всё ещё занят`)
  return !(await isUdpPortListening(port, host))
}

async function disableWgAdapters(send, epoch = null) {
  if (epoch != null && epoch !== wgApplyEpoch) return
  try {
    await execAsync(`ip link set ${TUNNEL_NAME} down`, { timeout: 5000 })
  } catch { /* ignore */ }
}

async function trySyncConf(runtimeDir, stableConf, send) {
  void runtimeDir
  try {
    await helperOut(['up', stableConf, lastWgGo || 'auto'], 45000)
    send?.('[WG] syncconf: повторный up')
    return await isTunnelUpAsync()
  } catch (e) {
    send?.(`[WG] syncconf: ${e?.message || e}`, 'W')
    return false
  }
}

async function forceStopWireGuard(isDev, dirname, send) {
  const epoch = wgApplyEpoch
  return enqueueWgStop(async () => {
    if (epoch !== wgApplyEpoch) {
      send?.('[WG] stop отменён — уже новый connect')
      return
    }
    if (!(await isWgStillPresentAsync())) return
    send?.('[WG] Остановка туннеля...')
    prepareRuntimeDir(isDev, dirname, send)
    try {
      await helperOut(['down'], 20000)
    } catch (e) {
      send?.(`[WG] down: ${e?.message || e}`, 'W')
      try {
        await execAsync(`ip link delete ${TUNNEL_NAME}`, { timeout: 5000 })
      } catch { /* ignore */ }
    }
    if (await isWgStillPresentAsync()) {
      send?.('[WG] wg-turn ещё активен после stop — повтор…', 'W')
      try { await helperOut(['down'], 15000) } catch { /* ignore */ }
    }
    if (!(await isWgStillPresentAsync())) {
      send?.('[WG] Туннель wg-turn снят')
    } else {
      send?.('[WG] Не удалось снять wg-turn — pkexec / sudo ip link delete wg-turn', 'E')
    }
  })
}

async function stopWireGuardTunnel(isDev, dirname, send, excludeIPs = []) {
  const epoch = wgApplyEpoch
  await forceStopWireGuard(isDev, dirname, send)
  await enqueueWgStop(async () => {
    if (epoch !== wgApplyEpoch) {
      send?.('[WG] bypass не снимаем — уже новый connect')
      return
    }
    await removeHostBypassRoutes(
      excludeIPs.length ? excludeIPs : [FALLBACK_BACKEND_IP],
      send,
      epoch,
    )
    try { await helperOut(['dns-restore'], 8000) } catch { /* ignore */ }
    if (epoch === wgApplyEpoch) {
      savedPhysicalGateway = null
    }
  })
}

async function applyWireGuardConfig(confPath, isDev, dirname, send, excludeIPs = [], options = {}) {
  await sleep(0)
  await waitWgStopIdle()
  const skipWdttWait = options.skipWdttWait === true
  const subnetOnly = options.subnetOnly === true
  const skipForceStop = options.skipForceStop === true
  const gatewayPromise = excludeIPs.length ? capturePhysicalGateway(send) : Promise.resolve(null)
  const runtimeDir = prepareRuntimeDir(isDev, dirname, send)
  if (!runtimeDir) {
    send('[WG] Нет silent-wg-helper — пересоберите Silent VPN для Linux')
    return false
  }

  let resolvedDns = WG_DNS
  if (fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      const allowed = subnetOnly
        ? '10.66.66.0/24'
        : buildAllowedIPsForLinux(excludeIPs, send)
      if (subnetOnly) {
        send?.('[WG] AllowedIPs = 10.66.66.0/24 (bootstrap/cred: только API)')
        conf = conf.replace(/^\s*DNS\s*=.*\r?\n/m, '')
      } else {
        send?.(`[WG] AllowedIPs = ${allowed} (полный туннель)`)
        const dnsLine = conf.match(/^\s*DNS\s*=\s*(.+)$/m)
        const dns = normalizeDnsValue(dnsLine ? dnsLine[1] : '', options.dnsOverride)
        resolvedDns = dns
        conf = conf.replace(/^\s*DNS\s*=.*\r?\n/m, '')
        conf = conf.replace(
          /(\[Interface\][^\[]*)/,
          m => `${m.trimEnd()}\nDNS = ${dns}\n`,
        )
        send?.(`[WG] DNS = ${dns}`)
      }
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${allowed}`)
      conf = normalizeWgConfText(conf)
      fs.writeFileSync(confPath, conf, 'utf8')
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

  const incomingConf = fs.existsSync(confPath) ? fs.readFileSync(confPath, 'utf8') : ''
  const oldIdentity = confCryptoIdentity(lastStableConfText())
  const newIdentity = confCryptoIdentity(incomingConf)
  const cryptoChanged = !!(oldIdentity && newIdentity && oldIdentity !== newIdentity)
  if (cryptoChanged) {
    send('[WG] ключи/peer сменились — полная переустановка, не syncconf')
  }
  const stableConf = copyStableConf(confPath)
  send(`[WG] Конфиг: ${stableConf}`)

  const adapterUp = await isTunnelUpAsync()
  const allowSync = skipForceStop && adapterUp && !cryptoChanged
  if (allowSync) {
    if (await trySyncConf(runtimeDir, stableConf, send)) {
      await gatewayPromise
      await finalizeTunnelUp(send, excludeIPs, subnetOnly, resolvedDns)
      send('[WG] Туннель активен (syncconf)')
      return true
    }
    send?.('[WG] syncconf не удался — переустановка…', 'W')
    await forceStopWireGuard(isDev, dirname, send)
    await sleep(200)
  } else if (adapterUp) {
    await forceStopWireGuard(isDev, dirname, send)
    await sleep(200)
  }

  const elevated = isProcessElevated()
  send(elevated
    ? '[WG] Процесс с правами root'
    : '[WG] Без root — нужен pkexec (пароль администратора) для туннеля')

  const wgGo = lastWgGo || findWireguardGo(isDev, dirname)
  try {
    await helperOut(['up', stableConf, wgGo], 90000)
  } catch (e) {
    const msg = String(e?.message || e)
    if (/pkexec|not found|77|dismiss|cancel|org.freedesktop.policykit/i.test(msg)) {
      send('[WG] pkexec отменён или недоступен. Запустите Silent VPN через sudo или установите policykit')
    } else {
      send('[WG] up: ' + msg.slice(0, 240))
    }
    return false
  }

  if (!(await waitForTunnelUp(25000, send))) {
    send('[WG] интерфейс не поднялся после up')
    return false
  }

  await gatewayPromise
  await finalizeTunnelUp(send, excludeIPs, subnetOnly, resolvedDns)
  send('[WG] Туннель активен')
  return true
}

module.exports = {
  TUNNEL_CONF_NAME,
  TUNNEL_NAME,
  FALLBACK_BACKEND_IP,
  isProcessElevated,
  waitForPort,
  waitForWdttProxy,
  waitForUdpPortFree,
  isUdpPortListening,
  waitForTunnelDown,
  isTunnelUp,
  isServiceRunning,
  isTunnelUpAsync,
  isServiceRunningAsync,
  resetWireGuardState: () => {},
  forceStopWireGuard,
  stopWireGuardTunnel,
  buildWgConfigFromApi,
  applyWireGuardConfig,
  addServerBypassRoutes,
  removeHostBypassRoutes,
  capturePhysicalGateway,
  normalizeWgConfText,
  waitWgStopIdle,
  beginWgApply,
  currentWgApplyEpoch,
  disableWgAdapters,
  trySyncConf,
  copyStableConf,
  prepareRuntimeDir,
  normalizeDnsValue,
  parseBypassTarget,
  buildAllowedIPsForLinux,
}
