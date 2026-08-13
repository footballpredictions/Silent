/**
 * olcrtc 2.0 cnc: olcrtc2-cnc.exe + sing-box TUN→SOCKS.
 * Паритет с Android (TG+YT через VPN): ipv4_only, без fake-ip,
 * block UDP/QUIC, dial peer до TUN, Telemost/WB prefetch.
 */
const { spawn, execSync } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const net = require('net')
const { app } = require('electron')

let cncProc = null
let singboxProc = null
let sessionActive = false
let ready = false
let onSessionDead = null
let healthWatchTimer = null
let lastTunnelActivityMs = 0
let peerClosedGraceTimer = null
let healthFailStreak = 0
/** missed_pong: не доверяем recent traffic / не молчим до socks_health. */
let peerLivenessSuspect = false

function setOlcrtc2SessionDeadHandler(fn) {
  onSessionDead = typeof fn === 'function' ? fn : null
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

function findExe(names) {
  const files = Array.isArray(names) ? names : [names]
  const roots = []
  if (!app.isPackaged) {
    roots.push(path.join(__dirname, '../../resources'))
    roots.push(path.join(__dirname, '../../../backend/olcrtc2/dist'))
    roots.push(path.join(__dirname, '../../../vendor/olcrtc'))
  }
  if (process.resourcesPath) roots.push(process.resourcesPath)
  for (const root of roots) {
    for (const f of files) {
      const p = path.join(root, f)
      if (fs.existsSync(p)) return p
    }
  }
  return null
}

function waitForPort(host, port, timeoutMs, log) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve) => {
    const tryOnce = () => {
      if (!sessionActive) {
        resolve(false)
        return
      }
      const socket = net.connect({ host, port }, () => {
        socket.end()
        resolve(true)
      })
      socket.on('error', () => {
        socket.destroy()
        if (Date.now() >= deadline || !sessionActive) {
          log?.(`[olcrtc2] timeout waiting ${host}:${port}`)
          resolve(false)
          return
        }
        setTimeout(tryOnce, 300)
      })
    }
    tryOnce()
  })
}

/** SOCKS5 CONNECT по домену (+ RFC1929). */
function socksDialDomainOnce(socksHost, socksPort, domain, timeoutMs = 2500, socksUser = '', socksPass = '') {
  return new Promise((resolve) => {
    const needAuth = Boolean(socksUser)
    const socket = net.connect({ host: socksHost, port: socksPort }, () => {
      socket.write(Buffer.from(needAuth ? [0x05, 0x01, 0x02] : [0x05, 0x01, 0x00]))
    })
    let stage = 0
    let buf = Buffer.alloc(0)
    const done = (ok) => {
      socket.destroy()
      resolve(ok)
    }
    const sendConnect = () => {
      const req = Buffer.alloc(5 + domain.length + 2)
      req[0] = 0x05
      req[1] = 0x01
      req[2] = 0x00
      req[3] = 0x03
      req[4] = domain.length
      req.write(domain, 5)
      req.writeUInt16BE(443, 5 + domain.length)
      socket.write(req)
      stage = 2
    }
    socket.on('data', (chunk) => {
      buf = Buffer.concat([buf, chunk])
      if (stage === 0) {
        if (buf.length < 2) return
        if (buf[0] !== 0x05) return done(false)
        const method = buf[1]
        buf = buf.subarray(2)
        if (needAuth) {
          if (method !== 0x02) return done(false)
          const ub = Buffer.from(socksUser, 'utf8')
          const pb = Buffer.from(socksPass, 'utf8')
          if (ub.length > 255 || pb.length > 255) return done(false)
          const auth = Buffer.alloc(3 + ub.length + pb.length)
          auth[0] = 0x01
          auth[1] = ub.length
          ub.copy(auth, 2)
          auth[2 + ub.length] = pb.length
          pb.copy(auth, 3 + ub.length)
          socket.write(auth)
          stage = 1
          return
        }
        if (method !== 0x00) return done(false)
        sendConnect()
      } else if (stage === 1) {
        if (buf.length < 2) return
        if (buf[0] !== 0x01 || buf[1] !== 0x00) return done(false)
        buf = buf.subarray(2)
        sendConnect()
      } else if (stage === 2) {
        if (buf.length < 2) return
        done(buf[1] === 0x00)
      }
    })
    socket.on('error', () => done(false))
    socket.setTimeout(timeoutMs, () => done(false))
  })
}

/** Ждём peer (как Android waitForSocksDial) — без пачки warm YouTube. */
async function waitForSocksDial(host, port, timeoutMs, log, socksUser = '', socksPass = '') {
  const deadline = Date.now() + timeoutMs
  const probeHost = 'www.gstatic.com'
  while (Date.now() < deadline && sessionActive) {
    const ok = await socksDialDomainOnce(host, port, probeHost, 3500, socksUser, socksPass)
    if (ok) {
      log?.(`[olcrtc2] SOCKS dial OK → ${probeHost}:443`)
      return true
    }
    await sleep(280)
  }
  return false
}

function killProc(proc, name, log) {
  if (!proc || proc.killed) return
  try {
    proc.kill()
  } catch (e) {
    log?.(`[olcrtc2] kill ${name}: ${e.message}`)
  }
}

function forceKillWindows(log) {
  if (process.platform !== 'win32') return
  let killed = 0
  for (const im of ['olcrtc2-cnc.exe', 'sing-box.exe']) {
    try {
      execSync(`taskkill /F /IM ${im} /T`, { stdio: 'ignore', windowsHide: true })
      killed += 1
    } catch {
      /* not running */
    }
  }
  if (killed > 0) log?.('[olcrtc2] forceKill windows processes')
}

function parseDnsServers(raw) {
  const list = String(raw || '')
    .split(',')
    .map((s) => s.trim())
    .filter((s) => s && !s.includes(':'))
  return list.length ? list : ['77.88.8.8', '77.88.8.1']
}

const IPV4_RE = /^\d{1,3}(?:\.\d{1,3}){3}$/

/** IPv4 из staticHosts + telemost/wb conn (TURN relay живёт на этих IP). */
function collectDirectCidrs(staticHosts, connFile, provider) {
  const ips = new Set()
  for (const v of Object.values(staticHosts || {})) {
    const ip = String(v || '').trim()
    if (IPV4_RE.test(ip)) ips.add(ip)
  }
  if (connFile && fs.existsSync(connFile)) {
    try {
      const raw = fs.readFileSync(connFile, 'utf8')
      const re = /\b(\d{1,3}(?:\.\d{1,3}){3})\b/g
      let m
      while ((m = re.exec(raw))) {
        const ip = m[1]
        // не тащим RFC1918/CGNAT из related candidates в route
        if (
          ip.startsWith('10.') ||
          ip.startsWith('127.') ||
          ip.startsWith('192.168.') ||
          /^172\.(1[6-9]|2\d|3[0-1])\./.test(ip) ||
          ip.startsWith('100.64.')
        ) {
          continue
        }
        ips.add(ip)
      }
    } catch {
      /* ignore */
    }
  }
  const cidrs = [...ips].map((ip) => `${ip}/32`)
  // Yandex media/TURN (37.9.*) — process_name на Win без админа часто молчит →
  // UDP block убивает refresh permissions через ~2–10 мин.
  if (provider === 'telemost') {
    cidrs.push('37.9.0.0/16')
  }
  // WB LiveKit (rtc-el/stream.wb.ru) — vp8channel ICE; без direct UDP refresh мрёт.
  if (provider === 'wbstream') {
    cidrs.push('185.62.192.0/18')
  }
  return [...new Set(cidrs)]
}

/**
 * sing-box: DNS TCP через SOCKS, ipv4_only, без fake-ip;
 * UDP/QUIC block; Cursor/IDE/cnc + TURN IP — direct (иначе peer мрёт на refresh).
 */
function renderSingboxConfig(
  socksHost,
  socksPort,
  dnsOverride = '',
  socksUser = '',
  socksPass = '',
  directCidrs = [],
  provider = 'telemost',
) {
  const dnsList = parseDnsServers(dnsOverride)
  const dnsServers = dnsList.map((ip, i) => ({
    tag: i === 0 ? 'remote' : `remote${i}`,
    address: `tcp://${ip}`,
    detour: 'olcrtc2-socks',
  }))
  const socksOutbound = {
    type: 'socks',
    tag: 'olcrtc2-socks',
    server: socksHost,
    server_port: socksPort,
    version: '5',
  }
  if (socksUser) {
    socksOutbound.username = socksUser
    socksOutbound.password = socksPass
  }
  const routeRules = [
    {
      process_name: [
        'Cursor.exe',
        'cursor.exe',
        'Silent VPN.exe',
        'Code.exe',
        'code.exe',
        // CRITICAL: ICE/TURN UDP в cnc. Без direct → refresh permissions мрёт.
        'olcrtc2-cnc.exe',
        'olcrtc.exe',
      ],
      outbound: 'direct',
    },
    {
      domain_suffix: [
        'cursor.sh',
        'cursor.com',
        'cursorapi.com',
        'anthropic.com',
        ...(provider === 'telemost'
          ? [
              'turn.tel.yandex.net',
              'stun.rtc.yandex.net',
              'goloom.strm.yandex.net',
              'telemost.yandex.ru',
              'cloud-api.yandex.ru',
            ]
          : [
              'stream.wb.ru',
              'rtc-el-01.wb.ru',
              'rtc-el-02.wb.ru',
              'wildberries.ru',
              'wb.ru',
            ]),
      ],
      outbound: 'direct',
    },
  ]
  if (directCidrs.length) {
    routeRules.push({
      ip_cidr: directCidrs,
      outbound: 'direct',
    })
  }
  routeRules.push(
    {
      port: [5353, 5355, 137, 138, 139, 1900],
      network: 'udp',
      outbound: 'block',
    },
    { port: 53, action: 'hijack-dns' },
    { protocol: 'quic', outbound: 'block' },
    { network: 'udp', outbound: 'block' },
  )
  return JSON.stringify(
    {
      log: { level: 'error' },
      dns: {
        servers: dnsServers,
        rules: [{ query_type: ['HTTPS', 'SVCB'], action: 'reject' }],
        strategy: 'ipv4_only',
        independent_cache: true,
        final: 'remote',
      },
      inbounds: [
        {
          type: 'tun',
          tag: 'tun-in',
          address: ['172.19.0.1/30'],
          auto_route: true,
          strict_route: true,
          stack: 'system',
          sniff: true,
          sniff_override_destination: true,
        },
      ],
      outbounds: [
        socksOutbound,
        { type: 'direct', tag: 'direct' },
        { type: 'block', tag: 'block' },
      ],
      route: {
        auto_detect_interface: true,
        rules: routeRules,
        final: 'olcrtc2-socks',
      },
    },
    null,
    2,
  )
}

/** Шум pion/ICE/WSL + штатные RST Windows — не красить лог красным (как olcrtc v1). */
function shouldMuteOlcrtc2Line(line) {
  return /\[ice\] TRACE:|\[sctp\] TRACE:|bufferedAmount|Failed to send packet|Failed to read from candidate|Could not determine PayloadType|Failed to accept RTP|stream is already closed|use of closed network connection|i\/o timeout|unreachable network|wsasendto|Ignore nominate|Failed to ping without candidate pairs|Connection is not possible yet|remote not ready|Failed to accept RTCP|Incoming unhandled RTCP|tunnel to dns\.google|tunnel to api2\.cursor\.sh|ICE connection state changed|peer connection state changed|signaling state changed|Setting new connection state|failed to get server reflexive|failed to allocate on TURN|Fail to refresh permissions|all retransmissions failed|operation not permitted|listen outbound packet|forcibly closed|wsarecv|aborted by the software|connection upload closed|connection download closed|request rejected, code=4|socks5: request rejected|exchange failed for .*\. IN (A|AAAA|HTTPS)|IN HTTPS: EOF|bad rdata|unpack request|process packet connection/i.test(
    line,
  )
}

/** sing-box stderr: RST при закрытии вкладок/QUIC→TCP — не ERROR в UI. */
function shouldMuteSingboxLine(line) {
  return shouldMuteOlcrtc2Line(line)
}

function cancelPeerClosedGrace() {
  if (peerClosedGraceTimer) {
    clearTimeout(peerClosedGraceTimer)
    peerClosedGraceTimer = null
  }
}

function cancelHealthWatch() {
  if (healthWatchTimer) {
    clearInterval(healthWatchTimer)
    healthWatchTimer = null
  }
}

function hasRecentTunnelTraffic(nowMs = Date.now()) {
  return nowMs - lastTunnelActivityMs < 25_000
}

function markPeerLivenessSuspect(reason, graceMs, log) {
  peerLivenessSuspect = true
  lastTunnelActivityMs = 0
  log?.(`[olcrtc2] peer suspect (${reason}) — force SOCKS check`)
  schedulePeerClosedGrace(reason, graceMs, log)
}

function notifySessionDead(code, reason, log) {
  if (!sessionActive && !ready) return
  sessionActive = false
  ready = false
  peerLivenessSuspect = false
  cancelHealthWatch()
  cancelPeerClosedGrace()
  killProc(singboxProc, 'sing-box', log)
  singboxProc = null
  killProc(cncProc, 'olcrtc2-cnc', log)
  cncProc = null
  try {
    onSessionDead?.({ code: code ?? 1, reason: reason || 'peer dead' })
  } catch {
    /* ignore */
  }
}

function schedulePeerClosedGrace(reason, graceMs, log) {
  if (!sessionActive || !ready) return
  cancelPeerClosedGrace()
  peerClosedGraceTimer = setTimeout(() => {
    peerClosedGraceTimer = null
    if (!sessionActive || !ready) return
    // missed_pong: recent traffic не спасает — иначе зелёный вис.
    if (hasRecentTunnelTraffic() && !peerLivenessSuspect) return
    log?.(`[olcrtc2] peer closed grace expired (${reason})`)
    notifySessionDead(1, reason, log)
  }, graceMs)
}

/** После tunnelReady: SOCKS-probe. Не убиваем при recent traffic / одном фейле. */
function startSocksHealthWatch(socksHost, socksPort, socksUser, socksPass, log) {
  cancelHealthWatch()
  healthFailStreak = 0
  const runProbe = async (tag) => {
    try {
      if (!sessionActive || !ready) return
      // Как Android: при живом tunnel to … не дергаем dial (крадёт полосу / ложные fail).
      if (hasRecentTunnelTraffic() && !peerLivenessSuspect) {
        healthFailStreak = 0
        log?.(`[olcrtc2] health ok (${tag}, recent traffic)`)
        return
      }
      const ok =
        (await socksDialDomainOnce(socksHost, socksPort, 'www.gstatic.com', 5000, socksUser, socksPass)) ||
        (await socksDialDomainOnce(
          socksHost,
          socksPort,
          'connectivitycheck.gstatic.com',
          4000,
          socksUser,
          socksPass,
        ))
      if (ok) {
        healthFailStreak = 0
        peerLivenessSuspect = false
        log?.(`[olcrtc2] health ok (${tag}, dial)`)
        return
      }
      healthFailStreak += 1
      const need = peerLivenessSuspect ? 1 : 2
      log?.(
        `[olcrtc2] SOCKS health miss ${healthFailStreak}/${need} (${tag})` +
          (peerLivenessSuspect ? ' suspect=yes' : '') +
          (hasRecentTunnelTraffic() ? ' recent=yes' : ''),
      )
      // Один таймаут gstatic под нагрузкой ≠ мёртвый peer (ложный kill ~3–5 мин).
      if (healthFailStreak < need || (hasRecentTunnelTraffic() && !peerLivenessSuspect)) return
      log?.('[olcrtc2] SOCKS health fail — peer мёртв после ready')
      notifySessionDead(1, 'socks_health_fail', log)
    } catch (e) {
      log?.(`[olcrtc2] health watch err: ${e?.message || e}`)
    }
  }
  setTimeout(() => void runProbe('t+45s'), 45_000)
  healthWatchTimer = setInterval(() => void runProbe('tick'), 45_000)
}

function pipeOlcrtc2Line(line, log) {
  if (!line || !log) return
  if (/tunnel to /i.test(line)) {
    lastTunnelActivityMs = Date.now()
    peerLivenessSuspect = false
    cancelPeerClosedGrace()
  }
  if (
    /connection state changed to connected|ICE connection state changed to connected|Setting new connection state: Connected|peer connection state changed:\s*connected/i.test(
      line,
    )
  ) {
    peerLivenessSuspect = false
    cancelPeerClosedGrace()
  }
  if (/peer restart detected|failed to connect link|subscriber media timeout|control missed pong|session closed/i.test(line)) {
    log(`[olcrtc2:peer] ${line.slice(0, 300)}`)
    if (/control missed pong/i.test(line)) {
      markPeerLivenessSuspect('missed_pong', 8_000, log)
    } else if (/failed to connect link|subscriber media timeout|session closed/i.test(line)) {
      markPeerLivenessSuspect('peer_liveness', 8_000, log)
    }
    return
  }
  if (/connection state changed to (closed|failed|disconnected)|peer connection state changed:\s*(closed|failed|disconnected)/i.test(line)) {
    log(`[olcrtc2:peer] ${line.slice(0, 300)}`)
    schedulePeerClosedGrace('peer_closed', 12_000, log)
    return
  }
  if (
    /SOCKS5 server listening|using prefetched|telemost:|wbstream:|vp8channel: peer latched|session .+ opened|olcrtc2-cnc ready/i.test(
      line,
    )
  ) {
    log(`[olcrtc2] ${line.slice(0, 300)}`)
    return
  }
  if (shouldMuteOlcrtc2Line(line)) return
  if (/\b(ERROR|FATAL)\b/i.test(line)) {
    log(`[olcrtc2:err] ${line.slice(0, 300)}`)
    return
  }
  if (/\bWARN\b/i.test(line)) {
    log(`[olcrtc2] ${line.slice(0, 300)}`)
    return
  }
  if (/\bINFO\b|^\d{4}\/\d{2}\/\d{2}/.test(line)) {
    // INFO только для редких вех — остальное mute
    if (/SOCKS5|peer latched|session .+ opened|prefetched|guest access/i.test(line)) {
      log(`[olcrtc2] ${line.slice(0, 300)}`)
    }
    return
  }
  log(`[olcrtc2] ${line.slice(0, 300)}`)
}

async function stopOlcrtc2Session(log) {
  sessionActive = false
  ready = false
  cancelHealthWatch()
  cancelPeerClosedGrace()
  lastTunnelActivityMs = 0
  healthFailStreak = 0
  peerLivenessSuspect = false
  killProc(singboxProc, 'sing-box', log)
  singboxProc = null
  killProc(cncProc, 'olcrtc2-cnc', log)
  cncProc = null
  forceKillWindows(log)
  await sleep(700)
}

function isOlcrtc2Alive() {
  return !!(cncProc && !cncProc.killed && sessionActive)
}

function isOlcrtc2SessionActive() {
  return sessionActive && ready
}

function formatStaticHosts(map) {
  if (!map || typeof map !== 'object') return ''
  return Object.entries(map)
    .filter(([h, ip]) => h && ip)
    .map(([h, ip]) => `${h}=${ip}`)
    .join(',')
}

async function beginOlcrtc2Session(config, { log, onReady } = {}) {
  // Полный сброс + пауза: иначе ICE цепляется к старому TUN 172.19.0.1.
  await stopOlcrtc2Session(log)
  const cncPath = findExe(['olcrtc2-cnc.exe', 'olcrtc2-cnc'])
  if (!cncPath) {
    return {
      error:
        'olcrtc2-cnc.exe не найден. Соберите: cd vendor/olcrtc && go build -o ../../pc/resources/olcrtc2-cnc.exe ./cmd/olcrtc2-cnc',
    }
  }
  const singboxPath = findExe(['sing-box.exe', 'sing-box'])
  if (!singboxPath) {
    return { error: 'sing-box.exe не найден в pc/resources/' }
  }

  const room = String(config.olcrtc_room || '').trim()
  const key = String(config.olcrtc_crypto_key || '').trim()
  const socksHost = String(config.olcrtc_socks_host || '127.0.0.1')
  const socksPort = Number(config.olcrtc_socks_port || 8808)
  if (!room || key.length !== 64) {
    return { error: 'olcrtc2: нужны room и crypto_key из /api/vpn/olcrtc2-config' }
  }

  const socksUser = `s${crypto.randomBytes(6).toString('hex')}`
  const socksPass = crypto.randomBytes(18).toString('base64url')
  const tmp = app.getPath('temp')
  const sbPath = path.join(tmp, 'silent-olcrtc2-singbox.json')
  const dnsOverride = String(config.dns_override || config.wg_dns || '').trim()
  log?.(`[olcrtc2] SOCKS auth user=${socksUser} (RFC1929 → cnc + sing-box)`)
  log?.(
    `[olcrtc2] DNS=${dnsOverride || '77.88.8.8,77.88.8.1'} (без fake-ip; ipv4_only; UDP/QUIC block)`,
  )

  const provider = String(config.olcrtc_provider || config.olcrtcProvider || 'telemost')
    .toLowerCase()
    .includes('wb')
    ? 'wbstream'
    : 'telemost'

  const dataDir = path.join(app.getPath('userData'), 'olcrtc2-data')
  fs.mkdirSync(dataDir, { recursive: true })

  let telemostConnFile = ''
  let wbConnFile = ''
  let staticHosts = {}
  try {
    const { prefetchTelemost, prefetchWbstream } = require('./olcrtcPrefetch')
    if (provider === 'telemost') {
      const pre = await prefetchTelemost(room, dataDir, log)
      if (pre?.connFile) telemostConnFile = pre.connFile
      if (pre?.staticHosts) staticHosts = { ...staticHosts, ...pre.staticHosts }
    } else if (provider === 'wbstream') {
      const pre = await prefetchWbstream(room, dataDir, log)
      if (pre?.staticHosts) staticHosts = { ...staticHosts, ...pre.staticHosts }
      // НЕ передаём OLCRTC_WBSTREAM_CONN_FILE: roomToken из prefetch короткоживущий
      // → peer мрёт через ~2–5 мин. Раньше prefetch 498 → Go guest сам → жили дольше.
      // STATIC_HOSTS + Go guest-register (как при antibot miss).
      wbConnFile = ''
      try {
        const { resolveHosts } = require('./olcrtcPrefetch')
        await resolveHosts(
          [
            'stream.wb.ru',
            'rtc-el-01.wb.ru',
            'rtc-el-02.wb.ru',
            'stream-meetup.wildberries.ru',
          ],
          staticHosts,
        )
      } catch {
        /* ignore */
      }
      log?.('[olcrtc2] WB: hosts only (без CONN_FILE — Go guest сам)')
    }
  } catch (e) {
    log?.(`[olcrtc2] prefetch: ${e.message}`)
  }

  const directCidrs = collectDirectCidrs(
    staticHosts,
    telemostConnFile || wbConnFile,
    provider,
  )
  fs.writeFileSync(
    sbPath,
    renderSingboxConfig(
      socksHost,
      socksPort,
      dnsOverride,
      socksUser,
      socksPass,
      directCidrs,
      provider,
    ),
    'utf8',
  )
  log?.(
    `[olcrtc2] sing-box direct cidrs=${directCidrs.length}` +
      (directCidrs.length ? ` (${directCidrs.slice(0, 6).join(',')}${directCidrs.length > 6 ? '…' : ''})` : ''),
  )

  const env = {
    ...process.env,
    OLCRTC2_MODE: provider,
    OLCRTC2_ROOM: room,
    OLCRTC2_KEY: key,
    OLCRTC2_SOCKS: `${socksHost}:${socksPort}`,
    OLCRTC2_SOCKS_USER: socksUser,
    OLCRTC2_SOCKS_PASS: socksPass,
  }
  if (telemostConnFile) {
    env.OLCRTC_TELEMOST_CONN_FILE = telemostConnFile
    log?.(`[olcrtc2] CONN_FILE=telemost-conn.json (prefetch, без Go→cloud-api)`)
  }
  if (wbConnFile) {
    env.OLCRTC_WBSTREAM_CONN_FILE = wbConnFile
    log?.(`[olcrtc2] CONN_FILE=wbstream-conn.json`)
  }
  const staticEnv = formatStaticHosts(staticHosts)
  if (staticEnv) {
    env.OLCRTC_STATIC_HOSTS = staticEnv
    log?.(`[olcrtc2] STATIC_HOSTS=${Object.keys(staticHosts).length}`)
  }

  sessionActive = true
  ready = false
  log?.(
    `[olcrtc2] start ${path.basename(cncPath)} mode=${provider} room=${room.slice(0, 40)} socks=${socksHost}:${socksPort} auth=on`,
  )

  cncProc = spawn(cncPath, [], {
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env,
  })
  cncProc.stdout?.on('data', (buf) => {
    for (const line of String(buf).split(/\r?\n/)) {
      pipeOlcrtc2Line(line.trim(), log)
    }
  })
  cncProc.stderr?.on('data', (buf) => {
    for (const line of String(buf).split(/\r?\n/)) {
      pipeOlcrtc2Line(line.trim(), log)
    }
  })
  cncProc.on('exit', (code) => {
    log?.(`[olcrtc2] exited code=${code}`)
    const wasReady = ready
    ready = false
    if (sessionActive) {
      sessionActive = false
      killProc(singboxProc, 'sing-box', log)
      singboxProc = null
      if (wasReady) {
        try {
          onSessionDead?.({ code, reason: 'olcrtc2_exit' })
        } catch {
          /* ignore */
        }
      }
    }
  })

  const portOk = await waitForPort(socksHost, socksPort, 90_000, log)
  if (!portOk || !sessionActive) {
    await stopOlcrtc2Session(log)
    return { error: 'olcrtc2: SOCKS не поднялся (комната/ключ/сота?)' }
  }
  log?.(`[olcrtc2] SOCKS listen ${socksHost}:${socksPort}`)

  // Как Android: peer dial ДО TUN — иначе sing-box заливает мёртвый SOCKS.
  log?.(`[olcrtc2] SOCKS dial… peer/ICE`)
  const dialOk = await waitForSocksDial(socksHost, socksPort, 45_000, log, socksUser, socksPass)
  if (!dialOk || !sessionActive) {
    await stopOlcrtc2Session(log)
    return { error: 'olcrtc2: SOCKS слушает, но peer не отвечает (dial timeout)' }
  }

  log?.(`[olcrtc2] SOCKS dial OK → sing-box (UDP/QUIC block; Cursor→direct)`)
  singboxProc = spawn(singboxPath, ['run', '-c', sbPath], {
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  singboxProc.stderr?.on('data', (buf) => {
    for (const line of String(buf).split(/\r?\n/)) {
      const t = line.trim()
      if (!t) continue
      if (shouldMuteSingboxLine(t)) continue
      if (/error|fatal/i.test(t)) {
        log?.(`[sing-box] ${t.slice(0, 200)}`)
      }
    }
  })
  singboxProc.on('exit', (code) => {
    log?.(`[sing-box] exited code=${code}`)
  })
  await sleep(600)
  // post-TUN soft probe (не hard-fail)
  await socksDialDomainOnce(socksHost, socksPort, 'www.gstatic.com', 3000, socksUser, socksPass)
  ready = true
  lastTunnelActivityMs = Date.now()
  startSocksHealthWatch(socksHost, socksPort, socksUser, socksPass, log)
  log?.(`[olcrtc2] tunnelReady (SOCKS + sing-box TUN; TG+YT via VPN)`)
  onReady?.()
  return { success: true }
}

module.exports = {
  beginOlcrtc2Session,
  stopOlcrtc2Session,
  isOlcrtc2Alive,
  isOlcrtc2SessionActive,
  setOlcrtc2SessionDeadHandler,
}
