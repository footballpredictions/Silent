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
const FALLBACK_BACKEND_IP = '132.243.234.162'
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

function findHelper(isDev, dirname) {
  const base = resourcesDir(isDev, dirname)
  const candidates = [
    SYSTEM_HELPER,
    path.join(base, 'mac', 'silent-wg-helper'),
    path.join(base, 'silent-wg-helper'),
  ]
  for (const p of candidates) {
    if (fs.existsSync(p)) return p
  }
  return null
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

function installHelperShell(bundledHelper) {
  const esc = (s) => String(s).replace(/'/g, `'\\''`)
  const h = esc(bundledHelper)
  const sys = esc(SYSTEM_HELPER)
  const plist = esc(HELPER_PLIST)
  const label = esc(HELPER_LABEL)
  return [
    `mkdir -p /Library/PrivilegedHelperTools /var/run/silent-vpn`,
    `cp '${h}' '${sys}'`,
    `chmod 755 '${sys}'`,
    `chown root:wheel '${sys}'`,
    `cat > '${plist}' <<'PLIST'`,
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">`,
    `<plist version="1.0"><dict>`,
    `<key>Label</key><string>ru.silent.vpn.helper</string>`,
    `<key>ProgramArguments</key><array>`,
    `<string>/Library/PrivilegedHelperTools/silent-vpn-wg-helper</string>`,
    `<string>serve</string>`,
    `</array>`,
    `<key>RunAtLoad</key><true/>`,
    `<key>KeepAlive</key><true/>`,
    `</dict></plist>`,
    `PLIST`,
    `launchctl bootout system/${label} 2>/dev/null || true`,
    `launchctl bootstrap system '${plist}'`,
    `launchctl enable system/${label}`,
    `launchctl kickstart -k system/${label}`,
  ].join('\n')
}

async function startHelperDaemonOnce() {
  if (await pingHelper()) return
  const helper = lastHelperPath || findHelper(false, __dirname) || SYSTEM_HELPER
  if (isProcessElevated() && helper && fs.existsSync(helper)) {
    spawn(helper, ['serve'], { detached: true, stdio: 'ignore' }).unref()
    if (await waitForHelperSocket(6000)) return
  }
  try {
    await execFileAsync('launchctl', ['kickstart', '-k', `system/${HELPER_LABEL}`], { timeout: 8000 })
    if (await waitForHelperSocket(6000)) return
  } catch { /* not installed yet */ }
  const bundled = (helper && fs.existsSync(helper) && helper !== SYSTEM_HELPER)
    ? helper
    : findHelper(false, __dirname)
  if (!bundled || !fs.existsSync(bundled)) {
    throw new Error('silent-wg-helper not found')
  }
  const script = installHelperShell(bundled)
  const osa = `do shell script ${JSON.stringify(script)} with administrator privileges`
  await execFileAsync('osascript', ['-e', osa], { timeout: 180000 })
  if (!(await waitForHelperSocket(15000))) {
    throw new Error('helper daemon did not start')
  }
}

async function ensureHelperDaemon() {
  if (await pingHelper()) return
  if (!daemonStartPromise) {
    daemonStartPromise = startHelperDaemonOnce().finally(() => {
      daemonStartPromise = null
    })
  }
  await daemonStartPromise
  if (!(await pingHelper())) {
    throw new Error('Silent VPN helper не запущен')
  }
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
  await ensureHelperDaemon()
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
    // WDTT dialViaLan: LocalAddr = LAN IP (creds_direct_other.go на darwin).
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
  const base = pickDnsServers(dnsValue)
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
  // Роутер первым: на части Wi‑Fi 8.8.8.8/публичный DNS таймаутится, а 192.168.x.1 работает.
  const gw = savedPhysicalGateway?.nextHop
  const servers = [...new Set([...(gw ? [gw] : []), ...base])]
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

/** DNS-серверы должны ходить мимо туннеля: иначе WDTT ещё не готов → lookup timeout → воркеры мрут. */
function dnsBypassIps(dnsValue = WG_DNS) {
  const fromMenu = pickDnsServers(dnsValue)
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
    .map(s => (s.includes('/') ? s : `${s}/32`))
  const gw = savedPhysicalGateway?.nextHop
  const gwCidr = gw ? [`${gw}/32`] : []
  return [...new Set([...fromMenu, ...gwCidr, ...EXTRA_DNS_BYPASS])]
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
  const skipForceStop = options.skipForceStop === true
  const gatewayPromise = excludeIPs.length ? capturePhysicalGateway(send) : Promise.resolve(null)
  const runtimeDir = prepareRuntimeDir(isDev, dirname, send)
  if (!runtimeDir) {
    send('[WG] Нет silent-wg-helper — пересоберите Silent VPN для Mac')
    return false
  }

  let resolvedDns = WG_DNS
  if (fs.existsSync(confPath)) {
    try {
      let conf = fs.readFileSync(confPath, 'utf8')
      const allowed = subnetOnly
        ? '10.66.66.0/24'
        : buildAllowedIPsForDarwin(excludeIPs, send)
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
    : '[WG] Туннель через helper (пароль только при первой установке helper)')

  await gatewayPromise
  // До up: host-route DNS/VK через LAN + protect table (TURN IP динамические).
  if (!subnetOnly) {
    const preBypass = [...new Set([...(excludeIPs || []), ...dnsBypassIps(resolvedDns)])]
    if (preBypass.length) {
      await addServerBypassRoutes(preBypass, send)
    }
    await enableLanProtect(send)
    await pinVkHosts(send)
  }

  const wgGo = lastWgGo || findWireguardGo(isDev, dirname)
  try {
    await helperOut(['up', stableConf, wgGo], 90000)
  } catch (e) {
    const msg = String(e?.message || e)
    if (/osascript|administrator|not found|77|dismiss|cancel|User canceled|helper daemon/i.test(msg)) {
      send('[WG] Нет прав на туннель. Разрешите установку helper (пароль один раз) или переустановите .dmg')
    } else {
      send('[WG] up: ' + msg.slice(0, 240))
    }
    return false
  }

  if (!(await waitForTunnelUp(25000, send))) {
    send('[WG] интерфейс не поднялся после up')
    return false
  }

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
