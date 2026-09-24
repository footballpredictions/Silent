/**
 * WireGuard macOS — тот же контракт, что Windows/Linux.
 * Туннель utun (wireguard-go), AllowedIPs 0.0.0.0/1 + 128.0.0.0/1,
 * bypass /32 через физический шлюз.
 * Права: LaunchDaemon после установки (пароль один раз) — дальше тумблер без пароля.
 */
const path = require('path')
const fs = require('fs')
const os = require('os')
const net = require('net')
const { exec, execFile, execFileSync, spawn } = require('child_process')
const { promisify } = require('util')
const execAsync = promisify(exec)
const execFileAsync = promisify(execFile)

const TUNNEL_NAME = 'utun'
const TUNNEL_CONF_NAME = 'wg-turn.conf'
const FALLBACK_BACKEND_IP = '89.125.188.100'
const WG_DNS = '1.1.1.1, 1.0.0.1, 77.88.8.8'
/** DHCP/Google DNS часто остаётся — route мимо WG, но nameserver ими не ставим. */
const EXTRA_DNS_BYPASS = ['8.8.8.8/32', '8.8.4.4/32']
const STABLE_CONF_DIR = path.join(os.homedir(), 'Library', 'Application Support', 'SilentVPN')
const SYSTEM_HELPER = '/Library/PrivilegedHelperTools/silent-vpn-wg-helper'
const HELPER_SOCK = '/var/run/silent-vpn/helper.sock'
const HELPER_PLIST = '/Library/LaunchDaemons/ru.silent.vpn.helper.plist'
const HELPER_LABEL = 'ru.silent.vpn.helper'

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
let daemonStartPromise = null

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

function findBundledHelper(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    path.join(base, 'mac', 'silent-wg-helper'),
    path.join(base, 'silent-wg-helper'),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return null
}

/** Для запуска: system (LaunchDaemon), иначе bundled из .app. */
function findHelper(isDev, dirname) {
  if (fs.existsSync(SYSTEM_HELPER)) return SYSTEM_HELPER
  return findBundledHelper(isDev, dirname)
}

function pingHelper(timeoutMs = 400) {
  return new Promise((resolve) => {
    const sock = net.connect({ path: HELPER_SOCK })
    const t = setTimeout(() => {
      sock.destroy()
      resolve(false)
    }, timeoutMs)
    sock.once('connect', () => {
      clearTimeout(t)
      sock.destroy()
      resolve(true)
    })
    sock.once('error', () => {
      clearTimeout(t)
      resolve(false)
    })
  })
}

function helperViaSocket(args, timeoutMs) {
  return new Promise((resolve, reject) => {
    const sock = net.connect({ path: HELPER_SOCK })
    let buf = ''
    const t = setTimeout(() => {
      sock.destroy()
      const err = new Error('helper socket timeout')
      err.code = 'ETIMEDOUT'
      reject(err)
    }, timeoutMs)
    sock.setEncoding('utf8')
    sock.once('connect', () => {
      sock.write(`${JSON.stringify({ args })}\n`)
    })
    sock.on('data', (chunk) => {
      buf += chunk
      const nl = buf.indexOf('\n')
      if (nl < 0) return
      clearTimeout(t)
      sock.end()
      try {
        const resp = JSON.parse(buf.slice(0, nl))
        if (resp && resp.ok) {
          resolve({ stdout: String(resp.out || ''), stderr: String(resp.err || '') })
          return
        }
        const err = new Error(String(resp?.err || resp?.out || 'helper failed').trim())
        err.code = resp?.code || 1
        err.stdout = String(resp?.out || '')
        err.stderr = String(resp?.err || '')
        reject(err)
      } catch (e) {
        reject(e)
      }
    })
    sock.once('error', (e) => {
      clearTimeout(t)
      reject(e)
    })
  })
}

async function waitForHelperSocket(ms = 8000) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    if (await pingHelper()) return true
    await sleep(150)
  }
  return pingHelper()
}

async function tryKickstartHelper() {
  try {
    await execFileAsync('launchctl', ['kickstart', '-k', `system/${HELPER_LABEL}`], { timeout: 8000 })
  } catch { /* ignore */ }
  if (await waitForHelperSocket(8000)) return true
  return pingHelper()
}

let helperLogSend = null

function installHelperFromApp(reason) {
  const { installSystemHelperOnce } = require('./macHelperInstall')
  return installSystemHelperOnce({
    bundledHelper: findBundledHelper(lastIsDev, lastDirname),
    systemHelper: SYSTEM_HELPER,
    plistPath: HELPER_PLIST,
    label: HELPER_LABEL,
    sockPath: HELPER_SOCK,
    reason,
    send: helperLogSend,
  })
}

function helperContentHash(filePath) {
  const crypto = require('crypto')
  const raw = fs.readFileSync(filePath)
  const norm = Buffer.from(String(raw).replace(/\r\n/g, '\n').replace(/\r/g, '\n'))
  return crypto.createHash('sha256').update(norm).digest('hex')
}

async function startHelperDaemonOnce() {
  if (await pingHelper()) return
  const helper = lastHelperPath || findHelper(lastIsDev, lastDirname) || SYSTEM_HELPER
  if (isProcessElevated() && helper && fs.existsSync(helper)) {
    spawn(helper, ['serve'], { detached: true, stdio: 'ignore' }).unref()
    if (await waitForHelperSocket(6000)) return
  }
  if (fs.existsSync(SYSTEM_HELPER) && await tryKickstartHelper()) return
  // Чистая установка из DMG: первый VPN (bootstrap входа) — ставим helper, пароль один раз.
  const installed = await installHelperFromApp(
    fs.existsSync(SYSTEM_HELPER) ? 'служба не отвечает' : 'первый запуск',
  )
  if (installed && await waitForHelperSocket(10000)) return
  if (!fs.existsSync(SYSTEM_HELPER)) {
    throw new Error('служба VPN не установлена — разрешите установку (пароль) или ./mac-force-helper.sh')
  }
  throw new Error('служба VPN не отвечает — перезапустите Silent VPN или ./mac-force-helper.sh')
}

async function ensureHelperDaemon(send) {
  if (await pingHelper()) {
    await maybeUpgradeSystemHelper(send)
    return
  }
  if (!daemonStartPromise) {
    daemonStartPromise = startHelperDaemonOnce().finally(() => {
      daemonStartPromise = null
    })
  }
  await daemonStartPromise
  if (!(await pingHelper())) {
    throw new Error('Silent VPN helper не запущен — ./mac-force-helper.sh')
  }
}

/** SHA system ≠ .app (DMG поверх старой установки) → одно обновление с паролем. */
let helperUpgradeTried = false
let lastIsDev = false
let lastDirname = __dirname

async function maybeUpgradeSystemHelper(send, force = false) {
  void force
  if (helperUpgradeTried) return false
  helperUpgradeTried = true
  try {
    const bundled = findBundledHelper(lastIsDev, lastDirname)
    if (!bundled || !fs.existsSync(bundled) || !fs.existsSync(SYSTEM_HELPER)) return false
    const hBundled = helperContentHash(bundled)
    const hSys = helperContentHash(SYSTEM_HELPER)
    if (hBundled === hSys) {
      send?.('[WG] helper: system актуален')
      return false
    }
    const log = send || helperLogSend
    log?.('[WG] helper в .app новее system — обновляю службу VPN', 'W')
    const saved = helperLogSend
    helperLogSend = log
    try {
      if (await installHelperFromApp('обновление')) {
        await waitForHelperSocket(10000)
        return true
      }
    } finally {
      helperLogSend = saved
    }
    return false
  } catch (e) {
    send?.(`[WG] helper check: ${e?.message || e}`, 'W')
    return false
  }
}

const COMPETITOR_PROCESS_NAMES = [
  'V2BOX', 'V2box', 'v2box',
  'Happ', 'Happ Plus', 'HappPlus',
  'Urban VPN Desktop', 'Urban VPN', 'UrbanVPN',
  'v2RayTun', 'v2raytun', 'V2RayTun',
  'freevpn.pw', 'FreeVPN.pw', 'freevpn', 'FreeVPN',
]

/** Без helper (user killall) — работает даже со старым PrivilegedHelperTools. */
async function killCompetitorVpnsLocal(send) {
  const hit = []
  for (const name of COMPETITOR_PROCESS_NAMES) {
    try {
      await execFileAsync('killall', ['-TERM', name], { timeout: 4000 })
      hit.push(name)
    } catch { /* not running */ }
  }
  await sleep(350)
  for (const name of COMPETITOR_PROCESS_NAMES) {
    try {
      await execFileAsync('killall', ['-KILL', name], { timeout: 4000 })
    } catch { /* ignore */ }
  }
  const uniq = [...new Set(hit)]
  send?.(`[WG] competitors-local ${uniq.length ? uniq.join(',') : 'noop'}`)
}

function findWireguardGo(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    path.join(base, 'mac', 'wireguard-go'),
    path.join(base, 'wireguard-go'),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return 'auto'
}

function prepareRuntimeDir(isDev, dirname, send) {
  lastIsDev = !!isDev
  lastDirname = dirname || __dirname
  if (send) helperLogSend = send
  const helper = findHelper(isDev, dirname)
  if (!helper) {
    send?.('[WG] Нет silent-wg-helper — пересоберите Mac-клиент')
    return null
  }
  lastHelperPath = helper
  lastRuntimeDir = path.dirname(helper)
  if (helper !== SYSTEM_HELPER) {
    try {
      fs.chmodSync(helper, 0o755)
    } catch { /* ignore */ }
  }
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

async function helperCmd(args, timeoutMs = 45000) {
  const helper = lastHelperPath
  if (!helper && !fs.existsSync(SYSTEM_HELPER)) {
    const err = new Error('silent-wg-helper not found')
    err.code = 'ENOHELPER'
    throw err
  }
  if (isProcessElevated() && helper) {
    return execFileAsync(helper, args, {
      encoding: 'utf8',
      timeout: timeoutMs,
      maxBuffer: 2 * 1024 * 1024,
    })
  }
  await ensureHelperDaemon(null)
  return helperViaSocket(args, timeoutMs)
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

function buildAllowedIPsForDarwin(excludeIPs, send) {
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

const { resolveWgMtu, WG_MTU_DEFAULT, WG_MTU_GAME } = require('./wgMtu')

/** Mac+WDTT: 1420 часто рвёт HTTPS (PMTU); handshake мелкий — «hs ok / Safari нет». */
function resolveDarwinMtu(config) {
  return Math.min(resolveWgMtu(config), 1280)
}

function buildWgConfigFromApi(config, listenPort = 9000) {
  const priv = (config.wg_private_key || '').trim()
  const pub = (config.server_public_key || '').trim()
  if (!priv || !pub) return null
  const addr = (config.wg_address || config.assigned_ip || '').trim()
  if (!addr) return null
  const dns = normalizeDnsValue(config.wg_dns || config.dns, config.dns_override)
  const mtu = resolveDarwinMtu(config)
  return `[Interface]
PrivateKey = ${priv}
Address = ${addr}
DNS = ${dns}
MTU = ${mtu}

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
    const out = await execAsync('ifconfig', { encoding: 'utf8', timeout: 4000 })
    return /utun\d+:[\s\S]*?inet 10\.66\./.test(String(out.stdout || out || ''))
  } catch {
    return false
  }
}

function isTunnelUp() {
  try {
    // Sync probe without helper: any utun with 10.66.
    const out = execFileSync('ifconfig', [], { encoding: 'utf8', timeout: 4000 })
    return /utun\d+:[\s\S]*?inet 10\.66\./.test(String(out || ''))
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
  const apply = (gw, iface) => {
    savedPhysicalGateway = { nextHop: gw, ifIndex: 0, alias: iface }
    // WDTT dialViaLan: LocalAddr + IP_BOUND_IF (creds_direct_darwin.go).
    // Как Android protect / Linux SO_MARK / iOS TURNBind — uplink WDTT мимо utun.
    if (iface) {
      try { process.env.SILENT_LAN_IFACE = String(iface) } catch { /* ignore */ }
    }
    send?.(`[WG] Шлюз до VPN: ${gw} (${iface})`)
    return savedPhysicalGateway
  }
  try {
    const { stdout } = await execAsync('route -n get default', { encoding: 'utf8', timeout: 5000 })
    const text = String(stdout || '')
    const gw = (text.match(/gateway:\s+(\d+\.\d+\.\d+\.\d+)/) || [])[1]
    const iface = (text.match(/interface:\s+(\S+)/) || [])[1]
    if (gw && iface && !String(iface).startsWith('utun')) return apply(gw, iface)
  } catch { /* helper fallback */ }
  try {
    const out = await helperOut(['gateway'], 12000)
    const parts = String(out || '').trim().split(/\s+/)
    if (parts.length >= 2 && /^\d+\.\d+\.\d+\.\d+$/.test(parts[0])) {
      return apply(parts[0], parts[1])
    }
  } catch (e) {
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

/** TURN IP из логов WDTT — без /32 bypass после 0/1 уходят в utun (Linux закрывает SO_MARK). */
const turnBypassIps = new Set()
let pendingLiveTurnIps = []
let liveTurnTimer = null

/**
 * Каждый новый TURN IP сразу в /32 bypass: рамп воркеров до 27 берёт новые relay
 * уже после full /1 — без маршрута их UDP уходит в utun (петля, hive timeout).
 */
function queueTurnIp(ip) {
  if (turnBypassIps.has(ip)) return 0
  turnBypassIps.add(ip)
  pendingLiveTurnIps.push(ip)
  return 1
}

function flushLiveTurnIps(send) {
  if (!savedPhysicalGateway?.nextHop || liveTurnTimer) return
  liveTurnTimer = setTimeout(() => {
    liveTurnTimer = null
    const batch = pendingLiveTurnIps
    pendingLiveTurnIps = []
    if (batch.length) {
      void addServerBypassRoutes(batch, send, { label: 'TURN' })
    }
  }, 100)
}

// legacy: «[VK Auth] [0] turn:IP:port?…»; vkcalls: «[VKCalls] turn_server.urls[0]=IP:port»
const TURN_LOG_RE = /(?:\bturns?:|turn_server\.urls\[\d+\]=)([A-Za-z0-9.-]+)/gi

function noteTurnEndpointFromLog(line, send) {
  const text = String(line || '')
  if (!/turns?:|turn_server\.urls/i.test(text)) return 0
  let n = 0
  const hosts = []
  TURN_LOG_RE.lastIndex = 0
  let m
  while ((m = TURN_LOG_RE.exec(text))) {
    const host = m[1].replace(/\.$/, '')
    if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(host)) n += queueTurnIp(host)
    else if (/[a-z]/i.test(host) && host.includes('.')) hosts.push(host)
  }
  for (const host of hosts) {
    require('dns').lookup(host, { family: 4, all: true }, (err, addrs) => {
      if (err || !addrs?.length) return
      let added = 0
      for (const a of addrs) added += queueTurnIp(a.address)
      if (added) flushLiveTurnIps(send)
    })
  }
  if (n) flushLiveTurnIps(send)
  return n
}

async function removeTurnBypassRoutes(send, epoch) {
  const ips = listTurnBypassIps()
  turnBypassIps.clear()
  pendingLiveTurnIps = []
  if (ips.length) await removeHostBypassRoutes(ips, send, epoch)
}

/** Лог при сбое phase2: куда реально идут TURN IP и растёт ли rx. */
async function logPhase2Diagnostics(send) {
  for (const ip of listTurnBypassIps().slice(0, 4)) {
    try {
      const { stdout } = await execAsync(`route -n get ${ip}`, { timeout: 4000, encoding: 'utf8' })
      const iface = (String(stdout).match(/interface:\s+(\S+)/) || [])[1] || '?'
      send?.(`[WG] diag route TURN ${ip} → ${iface}${iface.startsWith('utun') ? ' (ПЕТЛЯ через VPN)' : ''}`)
    } catch (e) {
      send?.(`[WG] diag route TURN ${ip}: ${String(e?.message || e).slice(0, 80)}`)
    }
  }
  try {
    const hs = await helperOut(['handshake'], 5000)
    const line = String(hs || '').trim().split(/\r?\n/).filter(Boolean).pop() || ''
    if (line) send?.(`[WG] diag ${line}`)
  } catch { /* ignore */ }
}

function listTurnBypassIps() {
  return [...turnBypassIps]
}

/** До expand AllowedIPs=/1: host-route peer+VK+TURN через en0 (работает и со старым wdtt). */
async function ensureTurnBypassBeforeFull(send, excludeIPs) {
  if (!turnBypassIps.size) {
    send?.('[WG] TURN bypass: ждём IP из логов WDTT (до 8с)…')
    for (let i = 0; i < 16 && !turnBypassIps.size; i++) {
      await sleep(500)
    }
  }
  const turns = listTurnBypassIps()
  const merged = [...new Set([...(excludeIPs || []), ...turns])]
  if (turns.length) {
    const head = turns.slice(0, 8).join(', ')
    send?.(
      `[WG] TURN bypass до full /1: ${head}${turns.length > 8 ? `…(+${turns.length - 8})` : ''} → LAN`,
    )
  } else {
    send?.(
      '[WG] TURN bypass: IP ещё нет — full /1 может убить WDTT (нужен wdtt с IP_BOUND_IF)',
      'W',
    )
  }
  if (merged.length) {
    await addServerBypassRoutes(merged, send, { label: 'TURN+API' })
  }
  return turns.length
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
  // Как на Windows/сервере: 1.1.1.1 + Яндекс 77.88.8.8 (не роутер — костыль после en0-бага).
  const servers = pickDnsServers(dnsValue)
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
    .slice(0, 3)
  if (!servers.length) return
  try {
    const out = await helperOut(['dns-set', TUNNEL_NAME, servers.join(',')], 12000)
    const lines = String(out || '').trim().split('\n').filter(Boolean)
    const hint = lines.join(' | ')
    send?.(`[WG] DNS на адаптере: ${servers.join(', ')}${hint ? ` (${hint})` : ''}`)
  } catch (e) {
    send?.(`[WG] DNS: ${e?.message || e}`, 'W')
  }
}

/** Только шлюз LAN в bypass. DNS 77.88/1.1.1.1 идут через utun (как на PC). */
function dnsBypassIps(dnsValue = WG_DNS) {
  void dnsValue
  const gw = savedPhysicalGateway?.nextHop
  return gw ? [`${gw}/32`] : []
}

async function pinVkHosts(send) {
  try {
    const { resolveVkExcludeHostMap, hostPinPairsFromMap } = require('./vkNetworkExcludes')
    const map = await resolveVkExcludeHostMap()
    const pairs = hostPinPairsFromMap(map)
    if (!pairs.length) {
      send?.('[WG] hosts-pin: нет IP VK (DNS до туннеля?)', 'W')
      return
    }
    const out = await helperOut(['hosts-pin', ...pairs], 12000)
    const hint = String(out || '').trim().split('\n').filter(Boolean).pop() || ''
    send?.(`[WG] hosts-pin VK: ${pairs.length}${hint ? ` (${hint})` : ''}`)
  } catch (e) {
    send?.(`[WG] hosts-pin: ${e?.message || e}`, 'W')
  }
}

async function restoreVkHosts(send) {
  try {
    await helperOut(['hosts-restore'], 8000)
  } catch (e) {
    send?.(`[WG] hosts-restore: ${e?.message || e}`, 'W')
  }
}

async function enableLanProtect(send) {
  if (!savedPhysicalGateway?.nextHop || !savedPhysicalGateway?.alias) {
    await capturePhysicalGateway(send)
  }
  const gw = savedPhysicalGateway
  if (!gw?.nextHop || !gw?.alias) {
    send?.('[WG] lan-protect: нет шлюза', 'W')
    return false
  }
  try {
    const out = await helperOut(['protect-on', gw.nextHop, gw.alias], 8000)
    const hint = String(out || '').trim().split('\n').filter(Boolean).pop() || ''
    send?.(`[WG] lan-protect (Android-like): ${hint || 'OK'}`)
    return true
  } catch (e) {
    send?.(`[WG] lan-protect: ${e?.message || e}`, 'W')
    return false
  }
}

async function disableLanProtect(send) {
  try {
    await helperOut(['protect-off'], 5000)
  } catch (e) {
    send?.(`[WG] lan-protect off: ${e?.message || e}`, 'W')
  }
}

async function blockIpv6Leak(send) {
  try {
    const out = await helperOut(['ipv6-block'], 8000)
    const hint = String(out || '').trim().split('\n').filter(Boolean).pop() || ''
    send?.(`[WG] IPv6 blackhole (без disable — меньше «нет интернета»): ${hint || 'OK'}`)
  } catch (e) {
    send?.(`[WG] IPv6 block: ${e?.message || e}`, 'W')
  }
}

async function restoreIpv6(send) {
  try {
    await helperOut(['ipv6-restore'], 8000)
  } catch (e) {
    send?.(`[WG] IPv6 restore: ${e?.message || e}`, 'W')
  }
}

let lastAppliedDns = WG_DNS

/** Периодически: NM может вернуть IPv6 RA / переписать resolv.conf. */
async function refreshTunnelGuards(send) {
  await enableLanProtect(send)
  await blockIpv6Leak(send)
  await applyWgDns(send, lastAppliedDns)
}

async function finalizeTunnelUp(send, excludeIPs, subnetOnly, dnsValue = WG_DNS) {
  const dnsIps = subnetOnly ? [] : dnsBypassIps(dnsValue)
  const merged = [...new Set([...(excludeIPs || []), ...dnsIps])]
  // Сначала host-route для DNS/API/VK — потом dns-set (иначе 1.1.1.1 уходит в мёртвый WG).
  if (merged.length) {
    await addServerBypassRoutes(merged, send)
  }
  if (!subnetOnly) {
    lastAppliedDns = dnsValue || WG_DNS
    await enableLanProtect(send)
    await blockIpv6Leak(send)
    // /etc/hosts до dns-set: WDTT auth (api.vk.me) не зависит от живого 8.8.8.8.
    await pinVkHosts(send)
    await applyWgDns(send, dnsValue)
  }
}

async function waitForTunnelUp(maxMs = 30000, send) {
  const deadline = Date.now() + maxMs
  while (Date.now() < deadline) {
    if (await isTunnelUpAsync()) return true
    await sleep(250)
  }
  const up = await isTunnelUpAsync()
  if (!up) send?.('[WG] интерфейс utun (WireGuard) не поднялся')
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
      send?.('[WG] Не удалось снять wg-turn — helper / sudo ip link delete wg-turn', 'E')
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
      [
        ...new Set([
          ...(excludeIPs.length ? excludeIPs : [FALLBACK_BACKEND_IP]),
          ...dnsBypassIps(),
        ]),
      ],
      send,
      epoch,
    )
    await removeTurnBypassRoutes(send, epoch)
    try { await helperOut(['dns-restore'], 8000) } catch { /* ignore */ }
    await restoreVkHosts(send)
    await disableLanProtect(send)
    await restoreIpv6(send)
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
  const wantFull = !subnetOnly
  const skipForceStop = options.skipForceStop === true
  const gatewayPromise = excludeIPs.length ? capturePhysicalGateway(send) : Promise.resolve(null)
  const runtimeDir = prepareRuntimeDir(isDev, dirname, send)
  if (!runtimeDir) {
    send('[WG] Нет silent-wg-helper — пересоберите Silent VPN для Mac')
    return false
  }

  // Phase1 всегда 10.66.66.0/24: лог 10:46 hs ok + rx=92 на full /1.
  // Сначала доказать data-plane к Улью без 0/1, потом expand (как iOS: bootstrap → attach).
  let resolvedDns = WG_DNS
  if (fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      const dnsLine = conf.match(/^\s*DNS\s*=\s*(.+)$/m)
      resolvedDns = normalizeDnsValue(dnsLine ? dnsLine[1] : '', options.dnsOverride)
      conf = conf.replace(/^\s*DNS\s*=.*\r?\n/m, '')
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, 'AllowedIPs = 10.66.66.0/24')
      conf = conf.replace(/^\s*MTU\s*=\s*(\d+)/im, (_, n) => `MTU = ${Math.min(Number(n) || 1200, 1280)}`)
      if (!/^\s*MTU\s*=/m.test(conf)) {
        conf = conf.replace(/(\[Interface\][^\[]*)/, m => `${m.trimEnd()}\nMTU = 1280\n`)
      }
      const mtuLog = conf.match(/^\s*MTU\s*=\s*(\d+)/im)
      if (mtuLog) send?.(`[WG] MTU = ${mtuLog[1]} (Mac clamp ≤1280)`)
      if (wantFull) {
        send?.('[WG] Mac phase1: AllowedIPs=10.66.66.0/24 (проверка data-plane до full)')
        send?.(`[WG] DNS (phase2) = ${resolvedDns}`)
      } else {
        send?.('[WG] AllowedIPs = 10.66.66.0/24 (bootstrap/cred: только API)')
      }
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
  let stableConf = copyStableConf(confPath)
  send(`[WG] Конфиг: ${stableConf}`)

  const adapterUp = await isTunnelUpAsync()
  const allowSync = skipForceStop && adapterUp && !cryptoChanged
  if (allowSync) {
    if (await trySyncConf(runtimeDir, stableConf, send)) {
      await gatewayPromise
      // helper мог появиться только сейчас (установка при первом connect) — до spawn protect упал
      await enableLanProtect(send)
      await pinVkHosts(send)
      await finalizeTunnelUp(send, excludeIPs, true, resolvedDns)
      const okSync = await finishDarwinConnect(send, {
        wantFull,
        confPath,
        excludeIPs,
        resolvedDns,
        isDev,
        dirname,
      })
      return okSync
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
    : '[WG] Туннель через службу VPN (helper; при первом запуске macOS спросит пароль один раз)')

  await gatewayPromise
  await killCompetitorVpnsLocal(send)
  try {
    const cOff = await helperOut(['competitors-off'], 12000)
    const line = String(cOff || '')
      .trim()
      .split(/\r?\n/)
      .filter(Boolean)
      .pop()
    if (line) send?.(`[WG] ${line}`)
  } catch (e) {
    const msg = String(e?.message || e)
    send?.(`[WG] competitors-off: ${msg}`, 'W')
    if (/unknown command/i.test(msg)) {
      send?.(
        '[WG] system helper устарел — пароль НЕ спрашиваем. Один раз: ./mac-force-helper.sh',
        'W',
      )
    }
  }
  // Phase1: bypass/protect до up — WDTT уже слушает; /1 ещё нет.
  {
    const preBypass = [...new Set([...(excludeIPs || []), ...dnsBypassIps(resolvedDns)])]
    if (preBypass.length) {
      await addServerBypassRoutes(preBypass, send)
    }
    await enableLanProtect(send)
    await pinVkHosts(send)
  }

  const wgGo = lastWgGo || findWireguardGo(isDev, dirname)
  try {
    const upOut = await helperOut(['up', stableConf, wgGo], 90000)
    const upLines = String(upOut || '').trim().split(/\r?\n/).filter(Boolean)
    for (const ln of upLines.slice(-6)) send?.(`[WG] ${ln}`)
  } catch (e) {
    const msg = String(e?.message || e)
    if (/osascript|administrator|not found|77|dismiss|cancel|User canceled|helper daemon|mac-force-helper/i.test(msg)) {
      send(`[WG] Служба VPN не запущена: ${msg.slice(0, 160)}`)
    } else {
      send('[WG] up: ' + msg.slice(0, 240))
    }
    return false
  }

  if (!(await waitForTunnelUp(25000, send))) {
    send('[WG] интерфейс не поднялся после up')
    return false
  }

  await finalizeTunnelUp(send, excludeIPs, true, resolvedDns)
  return finishDarwinConnect(send, {
    wantFull,
    confPath,
    excludeIPs,
    resolvedDns,
    isDev,
    dirname,
  })
}

/** Handshake + phase1 hive probe; при wantFull — reload /1+/1 и полный probe. */
async function finishDarwinConnect(send, { wantFull, confPath, excludeIPs, resolvedDns }) {
  let hsOk = false
  for (let i = 0; i < 20; i++) {
    try {
      const hs = await helperOut(['handshake'], 5000)
      const line = String(hs || '').trim().split(/\r?\n/).filter(Boolean).pop() || ''
      if (line) send?.(`[WG] ${line}`)
      if (/OK handshake/i.test(line) && !/age=-1/.test(line)) {
        hsOk = true
        break
      }
      if (/hs=\d+/i.test(line) && !/hs=0\b/.test(line)) {
        hsOk = true
        break
      }
    } catch (e) {
      const msg = String(e?.message || e)
      if (/OK handshake/i.test(msg) && /hs=[1-9]/i.test(msg)) {
        send?.(`[WG] ${msg.split('\n')[0]}`)
        hsOk = true
        break
      }
      if (i === 0 || i === 19) send?.(`[WG] handshake: ${msg.slice(0, 160)}`, 'W')
    }
    await sleep(500)
  }
  if (!hsOk) {
    send?.(
      '[WG] нет handshake с WDTT (127.0.0.1:9000). Скорее 0.0.0.0/1 перехватил loopback — обновите silent-wg-helper (lo-protect)',
      'E',
    )
  }
  const epoch = currentWgApplyEpoch()
  const hive = await tcpProbeNode('10.66.66.1', 8000, 8000)
  send?.(`[WG] probe phase1 tcp-hive=${hive.ok ? 'ok' : 'no:' + hive.why}`)
  let rx = 0
  try {
    const hs = await helperOut(['handshake'], 5000)
    const line = String(hs || '').trim().split(/\r?\n/).filter(Boolean).pop() || ''
    if (line) send?.(`[WG] after-phase1 ${line}`)
    rx = Number((line.match(/rx=(\d+)/) || [])[1] || 0)
  } catch { /* ignore */ }
  const phase1Ok = hive.ok || rx > 200
  if (epoch !== currentWgApplyEpoch()) {
    send?.('[WG] connect отменён (новый цикл) — не помечаем туннель активным')
    return false
  }
  if (!(await isTunnelUpAsync())) {
    send?.('[WG] utun пропал до конца connect — VPN НЕ активен')
    return false
  }
  if (!phase1Ok) {
    send?.(
      '[WG] phase1 data-plane мёртв (нет TCP к 10.66.66.1:8000, rx≈handshake). Тумблер сброшен — WG↔WDTT не отдаёт данные',
      'E',
    )
    return false
  }
  if (!wantFull) {
    send('[WG] Туннель активен')
    return true
  }

  // Лог 11:28: phase1 ok, после /1 hive timeout. Не replace_peers —
  // TURN UDP (динамические IP) без bypass/IP_BOUND_IF уходит в utun.
  await ensureTurnBypassBeforeFull(send, excludeIPs)
  send?.('[WG] Mac phase2: expand AllowedIPs → 0.0.0.0/1 + 128.0.0.0/1 (TURN bypass + без replace_peers)')
  const stablePath = path.join(STABLE_CONF_DIR, TUNNEL_CONF_NAME)
  const writableConf = fs.existsSync(confPath) ? confPath : stablePath
  try {
    let conf = fs.readFileSync(writableConf, 'utf8')
    const allowed = buildAllowedIPsForDarwin(excludeIPs, send)
    // DNS в conf пока не ставим — сначала routes+probe, иначе DNS через мёртвый /1.
    conf = conf.replace(/^\s*DNS\s*=.*\r?\n/m, '')
    conf = conf.replace(/AllowedIPs\s*=\s*.+/, `AllowedIPs = ${allowed}`)
    conf = normalizeWgConfText(conf)
    fs.writeFileSync(writableConf, conf, 'utf8')
    const stableConf = copyStableConf(writableConf)
    const out = await helperOut(['reload', stableConf], 30000)
    const line = String(out || '').trim().split(/\r?\n/).filter(Boolean).pop()
    if (line) send?.(`[WG] ${line}`)
  } catch (e) {
    send?.(`[WG] phase2 reload: ${String(e?.message || e).slice(0, 200)}`, 'E')
    return false
  }
  if (epoch !== currentWgApplyEpoch()) {
    send?.('[WG] connect отменён во время phase2 (новый цикл / vkcalls→legacy)')
    return false
  }
  if (!(await isTunnelUpAsync())) {
    send?.('[WG] utun пропал во время phase2 — не rollback на чужой connect')
    return false
  }
  // Сразу проверить Улей ДО dns-set (лог 11:15/11:28: после full tcp-hive умер).
  const hive2 = await tcpProbeNode('10.66.66.1', 8000, 8000)
  send?.(`[WG] probe phase2 tcp-hive=${hive2.ok ? 'ok' : 'no:' + hive2.why}`)
  if (!hive2.ok) {
    // Повтор: новые TURN могли появиться после reload.
    await ensureTurnBypassBeforeFull(send, excludeIPs)
    const hiveRetry = await tcpProbeNode('10.66.66.1', 8000, 6000)
    send?.(`[WG] probe phase2-retry tcp-hive=${hiveRetry.ok ? 'ok' : 'no:' + hiveRetry.why}`)
    if (hiveRetry.ok) {
      await finalizeTunnelUp(send, [...new Set([...(excludeIPs || []), ...listTurnBypassIps()])], false, resolvedDns)
      send('[WG] Туннель активен')
      return true
    }
    await logPhase2Diagnostics(send)
    send?.(
      '[WG] phase2 сломал data-plane: TURN/WDTT в петле utun (нужен wdtt-client с [LAN] IP_BOUND_IF + TURN /32 bypass). Откат /24, тумблер OFF',
      'E',
    )
    try {
      const src = fs.existsSync(writableConf) ? writableConf : stablePath
      let conf = fs.readFileSync(src, 'utf8')
      conf = conf.replace(/AllowedIPs\s*=\s*.+/, 'AllowedIPs = 10.66.66.0/24')
      conf = conf.replace(/^\s*DNS\s*=.*\r?\n/m, '')
      conf = normalizeWgConfText(conf)
      fs.writeFileSync(src, conf, 'utf8')
      const stableConf = copyStableConf(src)
      await helperOut(['reload', stableConf], 30000)
      send?.('[WG] rollback phase1 OK — интернет через Wi‑Fi, full VPN не активен')
    } catch (e) {
      send?.(`[WG] rollback: ${String(e?.message || e).slice(0, 160)}`, 'E')
    }
    // Не «активен»: сайты ок / YouTube нет — пользователь думает VPN вкл (лог 11:30).
    return false
  }
  await finalizeTunnelUp(
    send,
    [...new Set([...(excludeIPs || []), ...listTurnBypassIps()])],
    false,
    resolvedDns,
  )
  if (epoch !== currentWgApplyEpoch()) {
    send?.('[WG] connect отменён после phase2')
    return false
  }
  const cf = await tcpProbeNode('1.1.1.1', 443, 5000)
  send?.(`[WG] probe phase2 tcp-cf=${cf.ok ? 'ok' : 'no:' + cf.why}`)
  if (!cf.ok) {
    send?.('[WG] phase2: Улей ок, интернет (1.1.1.1) нет — DNS/маршрут; туннель всё же активен', 'W')
  }
  send('[WG] Туннель активен')
  return true
}

/** TCP через туннель из Electron (не LaunchDaemon python — лог 10:19 PermissionError). */
function tcpProbeNode(host, port, timeoutMs = 5000) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port, family: 4 })
    let done = false
    const finish = (ok, why) => {
      if (done) return
      done = true
      try {
        socket.destroy()
      } catch (_) {}
      resolve({ ok, why })
    }
    socket.setTimeout(timeoutMs)
    socket.once('connect', () => finish(true, 'ok'))
    socket.once('timeout', () => finish(false, 'timeout'))
    socket.once('error', (e) => finish(false, String(e?.code || e?.message || e).slice(0, 40)))
  })
}

/** @returns {Promise<boolean>} true если route→utun и tcp к улью или 1.1.1.1 жив */
async function probeInternetFromMain(send) {
  const probeIp = '9.9.9.9'
  let routeOk = false
  let dataOk = false
  try {
    const { stdout } = await execAsync(`route -n get ${probeIp}`, { timeout: 4000, encoding: 'utf8' })
    const text = String(stdout || '')
    let iface = '?'
    for (const line of text.split('\n')) {
      if (line.trim().startsWith('interface:')) iface = line.split(':')[1].trim()
    }
    if (iface.startsWith('utun')) {
      routeOk = true
      send?.(`[WG] probe route ${probeIp} → ${iface} OK`)
    } else {
      send?.(
        `[WG] probe route ${probeIp} → ${iface} FAIL (должен быть utun — трафик мимо VPN)`,
      )
    }
  } catch (e) {
    send?.(`[WG] probe route: ${e?.message || e}`)
  }
  // Node TCP первым: helper python на Mac даёт PermissionError (EPERM) даже когда путь жив.
  for (const [label, host, port] of [
    ['hive', '10.66.66.1', 8000],
    ['cf', '1.1.1.1', 443],
  ]) {
    const r = await tcpProbeNode(host, port, 5000)
    send?.(`[WG] probe node tcp-${label}=${r.ok ? 'ok' : 'no:' + r.why}`)
    if (r.ok) dataOk = true
  }
  try {
    const out = await helperOut(['probe'], 20000)
    const line = String(out || '').trim().split(/\r?\n/).filter(Boolean).pop() || out
    send?.(`[WG] ${line || 'probe helper empty'}`)
    if (/tcp-hive=ok|tcp-cf=ok/.test(String(line))) dataOk = true
  } catch (e) {
    const raw = String(e?.message || e)
    const msg = raw.trim().split(/\r?\n/).filter(Boolean).pop() || raw.slice(0, 220)
    send?.(`[WG] probe helper: ${msg}`)
    if (/tcp-hive=ok|tcp-cf=ok/.test(msg)) dataOk = true
  }
  try {
    await execAsync(`ping -c 1 -W 2000 ${probeIp}`, { timeout: 5000, encoding: 'utf8' })
    send?.(`[WG] probe ping ${probeIp} OK`)
  } catch {
    send?.(`[WG] probe ping ${probeIp} no-reply (ICMP; смотри tcp в probe helper)`)
  }
  try {
    const hs = await helperOut(['handshake'], 5000)
    const line = String(hs || '').trim().split(/\r?\n/).filter(Boolean).pop() || ''
    if (line) send?.(`[WG] after-probe ${line}`)
    const rx = Number((line.match(/rx=(\d+)/) || [])[1] || 0)
    // rx>200 недостаточно: лог 11:15 phase1 дал rx=188, после мёртвого full rx=284 — ложный OK.
    if (rx > 2000) dataOk = true
  } catch (e) {
    send?.(`[WG] after-probe handshake: ${String(e?.message || e).slice(0, 160)}`)
  }
  const gw = savedPhysicalGateway?.nextHop
  if (gw) {
    try {
      await execAsync(`ping -c 1 -W 1500 ${gw}`, { timeout: 4000, encoding: 'utf8' })
      send?.(`[WG] probe ping LAN ${gw} OK`)
    } catch {
      send?.(`[WG] probe ping LAN ${gw} FAIL`)
    }
  }
  return !!(routeOk && dataOk)
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
  resolveWgMtu: resolveDarwinMtu,
  WG_MTU_DEFAULT,
  WG_MTU_GAME,
  applyWireGuardConfig,
  probeTunnelGateway: () => Promise.resolve(false),
  addServerBypassRoutes,
  noteTurnEndpointFromLog,
  listTurnBypassIps,
  ensureTurnBypassBeforeFull,
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
  buildAllowedIPsForDarwin,
  dnsBypassIps,
  pinVkHosts,
  capturePhysicalGateway,
  enableLanProtect,
  refreshTunnelGuards,
  SYSTEM_HELPER,
  HELPER_SOCK,
  HELPER_PLIST,
}
