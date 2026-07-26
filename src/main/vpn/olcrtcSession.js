/**
 * Debug-only: olcrtc cnc (SOCKS5) + sing-box TUN → SOCKS.
 * Не трогает WDTT/WireGuard.
 */
const { spawn, execSync } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const path = require('path')
const net = require('net')
const { app } = require('electron')
const { prefetchTelemost, prefetchWbstream } = require('./olcrtcPrefetch')

/** Случайный login/pass на сессию — SOCKS без auth = любой локальный процесс жжёт peer/room. */
function generateSocksCreds() {
  const user = `s${crypto.randomBytes(6).toString('hex')}`
  const pass = crypto.randomBytes(18).toString('base64url')
  return { user, pass }
}

let olcrtcProc = null
let singboxProc = null
let sessionActive = false
let ready = false
/** Последние строки stderr olcrtc — на timeout показать причину. */
let lastOlcrtcLines = []

function pushOlcrtcLine(line) {
  lastOlcrtcLines.push(line)
  if (lastOlcrtcLines.length > 40) lastOlcrtcLines.shift()
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms))
}

function findExe(names) {
  const files = Array.isArray(names) ? names : [names]
  const roots = []
  if (!app.isPackaged) {
    roots.push(path.join(__dirname, '../../resources'))
    roots.push(path.join(__dirname, '../../olcrtc'))
    roots.push(path.join(__dirname, '../../vendor'))
  }
  if (process.resourcesPath) roots.push(process.resourcesPath)
  for (const root of roots) {
    for (const f of files) {
      const p = path.join(root, f)
      if (fs.existsSync(p)) return p
      const nested = path.join(root, 'olcrtc', f)
      if (fs.existsSync(nested)) return nested
      const nested2 = path.join(root, 'sing-box', f)
      if (fs.existsSync(nested2)) return nested2
      // electron-builder extraResources: resources/olcrtc.exe → app.asar.unpacked sibling
      const flat = path.join(root, path.basename(f))
      if (fs.existsSync(flat)) return flat
    }
  }
  return null
}

function waitForPort(host, port, timeoutMs, log) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve) => {
    const tryOnce = () => {
      const socket = net.connect({ host, port }, () => {
        socket.end()
        resolve(true)
      })
      socket.on('error', () => {
        socket.destroy()
        if (Date.now() >= deadline) {
          log?.(`[olcrtc] timeout waiting ${host}:${port}`)
          resolve(false)
          return
        }
        setTimeout(tryOnce, 300)
      })
    }
    tryOnce()
  })
}

/** Один SOCKS5 CONNECT по домену (peer резолвит DNS). RFC1929 если user/pass заданы. */
function socksDialDomainOnce(socksHost, socksPort, domain, timeoutMs = 2500, socksUser = '', socksPass = '') {
  return new Promise((resolve) => {
    const needAuth = Boolean(socksUser)
    const socket = net.connect({ host: socksHost, port: socksPort }, () => {
      // method 0x02 = username/password; 0x00 = no auth
      socket.write(Buffer.from(needAuth ? [0x05, 0x01, 0x02] : [0x05, 0x01, 0x00]))
    })
    let stage = 0 // 0=greet, 1=auth, 2=connect-resp
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

/**
 * Ждём стабильный peer: 2 успешных dial подряд + параллельный warm популярных доменов
 * (сайты не ждут минуту после ready).
 */
async function waitForSocksDial(host, port, timeoutMs, log, socksUser = '', socksPass = '') {
  const deadline = Date.now() + timeoutMs
  const probeHost = 'www.gstatic.com'
  const warmHosts = [
    probeHost,
    'dns.google',
    'www.cloudflare.com',
    'www.youtube.com',
    'www.google.com',
  ]
  let streak = 0
  while (Date.now() < deadline) {
    const ok = await socksDialDomainOnce(host, port, probeHost, 2800, socksUser, socksPass)
    if (!ok) {
      streak = 0
      await new Promise((r) => setTimeout(r, 280))
      continue
    }
    streak += 1
    if (streak < 2) {
      await new Promise((r) => setTimeout(r, 200))
      continue
    }
    log?.(`[olcrtc] SOCKS dial OK ×2 → ${probeHost}:443 (auth=on)`)
    // Прогрев DNS на peer (не блокируем ready дольше ~1с)
    await Promise.race([
      Promise.allSettled(
        warmHosts.map((d) => socksDialDomainOnce(host, port, d, 2000, socksUser, socksPass)),
      ),
      new Promise((r) => setTimeout(r, 1000)),
    ])
    log?.(`[olcrtc] SOCKS warm done (${warmHosts.length} hosts)`)
    return true
  }
  log?.(`[olcrtc] SOCKS dial timeout (peer/DNS ещё не готовы)`)
  return false
}

function killProc(proc, name, log) {
  if (!proc) return
  try {
    proc.kill()
  } catch (e) {
    log?.(`[olcrtc] kill ${name}: ${e.message || e}`)
  }
}

function stopOlcrtcSession(log) {
  ready = false
  sessionActive = false
  killProc(singboxProc, 'sing-box', log)
  singboxProc = null
  killProc(olcrtcProc, 'olcrtc', log)
  olcrtcProc = null
  try {
    execSync('taskkill /F /IM olcrtc.exe /T', { stdio: 'ignore', windowsHide: true })
  } catch { /* ignore */ }
  try {
    execSync('taskkill /F /IM sing-box.exe /T', { stdio: 'ignore', windowsHide: true })
  } catch { /* ignore */ }
  // Дать Win снять TUN 172.19.0.1 — иначе ICE ходит в мёртвый iface → unreachable.
  log?.('[olcrtc] session stopped')
}

async function stopOlcrtcSessionAndSettle(log) {
  stopOlcrtcSession(log)
  await sleep(600)
}

let onSessionDead = null

/** main.js: при смерти peer сбросить vpnOlcrtcMode и UI. */
function setOlcrtcSessionDeadHandler(fn) {
  onSessionDead = typeof fn === 'function' ? fn : null
}

function notifySessionDead(code, reason) {
  try {
    onSessionDead?.({ code, reason })
  } catch { /* ignore */ }
}

function isOlcrtcSessionActive() {
  return sessionActive && ready
}

function isOlcrtcAlive() {
  if (!olcrtcProc) return false
  try {
    return olcrtcProc.exitCode === null && !olcrtcProc.killed
  } catch {
    return false
  }
}

function renderClientYaml(config) {
  const provider = String(config.olcrtc_provider || config.olcrtcProvider || 'telemost')
  const room = String(config.olcrtc_room || config.olcrtcRoom || '').trim()
  const key = String(config.olcrtc_crypto_key || config.olcrtcCryptoKey || '').trim()
  let transport = String(config.olcrtc_transport || config.olcrtcTransport || '').trim()
  if (!transport) {
    transport =
      provider === 'telemost' || provider === 'wbstream' ? 'vp8channel' : 'datachannel'
  }
  const socksHost = String(config.olcrtc_socks_host || '127.0.0.1')
  const socksPort = Number(config.olcrtc_socks_port || 8808)
  const socksUser = String(config.olcrtc_socks_user || '')
  const socksPass = String(config.olcrtc_socks_pass || '')
  // JWT WB только на srv — клиенту guest. Не прокидывать auth_token.
  if (!room || key.length !== 64) {
    throw new Error('olcrtc: нужны room и crypto_key (64 hex) из /api/vpn/olcrtc-config')
  }
  const socksLines = [
    'socks:',
    `  host: "${socksHost}"`,
    `  port: ${socksPort}`,
  ]
  if (socksUser) {
    socksLines.push(`  user: "${socksUser.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`)
    socksLines.push(`  pass: "${socksPass.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`)
  }
  // Community URI: vp8-fps=60 — ближе к потолку SFU (~10 Мбит Telemost).
  const vp8Lines =
    transport === 'vp8channel' ? ['vp8:', '  fps: 60', '  batch_size: 64'] : []
  return [
    'mode: cnc',
    'auth:',
    `  provider: ${provider}`,
    'room:',
    `  id: "${room}"`,
    'crypto:',
    `  key: "${key}"`,
    'net:',
    `  transport: ${transport}`,
    '  dns: "1.1.1.1:53"',
    ...socksLines,
    ...vp8Lines,
    'data: data',
    '',
  ].join('\n')
}

function renderSingboxConfig(socksHost, socksPort, socksUser = '', socksPass = '') {
  // fake-ip + sniff: не гоняем DNS через peer на каждый сайт.
  // HTTPS/SVCB RR через SOCKS часто EOF — reject.
  // hijack только :53 (не protocol=dns) — иначе Win LLMNR/мусор → «bad rdata».
  return JSON.stringify(
    {
      log: { level: 'error' },
      dns: {
        servers: [
          {
            tag: 'remote',
            address: 'tcp://8.8.8.8',
            detour: 'olcrtc-socks',
          },
          {
            tag: 'fakeip',
            address: 'fakeip',
          },
        ],
        rules: [
          { query_type: ['HTTPS', 'SVCB'], action: 'reject' },
          { query_type: ['A', 'AAAA'], server: 'fakeip' },
        ],
        fakeip: {
          enabled: true,
          inet4_range: '198.18.0.0/15',
        },
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
        {
          type: 'socks',
          tag: 'olcrtc-socks',
          server: socksHost,
          server_port: socksPort,
          version: '5',
          ...(socksUser
            ? { username: socksUser, password: socksPass || '' }
            : {}),
        },
        { type: 'direct', tag: 'direct' },
        { type: 'block', tag: 'block' },
      ],
      route: {
        auto_detect_interface: true,
        rules: [
          {
            port: [5353, 5355, 137, 138, 139, 1900],
            network: 'udp',
            outbound: 'block',
          },
          { port: 53, action: 'hijack-dns' },
          { protocol: 'quic', outbound: 'block' },
          { network: 'udp', outbound: 'block' },
        ],
        final: 'olcrtc-socks',
      },
    },
    null,
    2,
  )
}

/**
 * @returns {Promise<{ success?: boolean, error?: string }>}
 */
async function beginOlcrtcSession(config, { log, onReady } = {}) {
  // Полный сброс + пауза: иначе ICE цепляется к 172.19.0.1 (старый sing-box TUN).
  await stopOlcrtcSessionAndSettle(log)
  lastOlcrtcLines = []
  const olcrtcPath = findExe(['olcrtc.exe', 'olcrtc'])
  if (!olcrtcPath) {
    return {
      error:
        'olcrtc.exe не найден. Положите в pc/resources/olcrtc.exe (см. github.com/openlibrecommunity/olcrtc)',
    }
  }
  const singboxPath = findExe(['sing-box.exe', 'sing-box'])
  if (!singboxPath) {
    return {
      error:
        'sing-box.exe не найден. Положите в pc/resources/sing-box.exe (TUN→SOCKS). Без него olcrtc SOCKS-only.',
    }
  }

  const socksHost = String(config.olcrtc_socks_host || '127.0.0.1')
  const socksPort = Number(config.olcrtc_socks_port || 8808)
  const { user: socksUser, pass: socksPass } = generateSocksCreds()
  config.olcrtc_socks_user = socksUser
  config.olcrtc_socks_pass = socksPass
  const provider = String(config.olcrtc_provider || 'telemost').toLowerCase()
  const room = String(config.olcrtc_room || '').trim()
  let yaml
  try {
    yaml = renderClientYaml(config)
  } catch (e) {
    return { error: e.message || String(e) }
  }

  const tmp = app.getPath('temp')
  const dataDir = path.join(tmp, 'silent-olcrtc-data')
  fs.mkdirSync(dataDir, { recursive: true })
  const yamlPath = path.join(tmp, 'silent-olcrtc-client.yaml')
  const sbPath = path.join(tmp, 'silent-olcrtc-singbox.json')
  yaml = yaml.replace(/\ndata: data\n/, `\ndata: "${dataDir.replace(/\\/g, '/')}"\n`)
  fs.writeFileSync(yamlPath, yaml, 'utf8')
  fs.writeFileSync(sbPath, renderSingboxConfig(socksHost, socksPort, socksUser, socksPass), 'utf8')
  log?.(`[olcrtc] SOCKS auth user=${socksUser} (per-session)`)

  let connFile = null
  let staticHosts = {}
  if (provider === 'telemost') {
    const pre = await prefetchTelemost(room, dataDir, log)
    connFile = pre.connFile || null
    staticHosts = pre.staticHosts || {}
  } else if (provider === 'wbstream') {
    const pre = await prefetchWbstream(room, dataDir, log)
    connFile = pre.connFile || null
    staticHosts = pre.staticHosts || {}
  }

  const env = { ...process.env }
  if (connFile && fs.existsSync(connFile)) {
    if (provider === 'telemost') env.OLCRTC_TELEMOST_CONN_FILE = connFile
    if (provider === 'wbstream') env.OLCRTC_WBSTREAM_CONN_FILE = connFile
  }
  const hostPairs = Object.entries(staticHosts)
  if (hostPairs.length) {
    env.OLCRTC_STATIC_HOSTS = hostPairs.map(([h, ip]) => `${h}=${ip}`).join(';')
    log?.(`[olcrtc] STATIC_HOSTS=${hostPairs.length}`)
  }

  sessionActive = true
  ready = false
  log?.(`[olcrtc] start ${olcrtcPath}`)
  log?.(
    `[olcrtc] provider=${provider} room=${room.slice(0, 60)} prefetch=${connFile ? 'yes' : 'no'} yaml=${yamlPath}`,
  )

  olcrtcProc = spawn(olcrtcPath, [yamlPath], {
    cwd: dataDir,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env,
  })
  let earlyExitCode = null
  let peerPendingLogged = false
  olcrtcProc.stdout?.on('data', (buf) => {
    const line = String(buf).trim()
    if (!line) return
    pushOlcrtcLine(line)
    if (
      /\[ice\] TRACE:|\[sctp\] TRACE:|bufferedAmount|\[xmpp|Failed to send packet|unreachable network|wsasendto/i.test(
        line,
      )
    ) {
      return
    }
    log?.(`[olcrtc] ${line.slice(0, 300)}`)
  })
  olcrtcProc.stderr?.on('data', (buf) => {
    const line = String(buf).trim()
    if (!line) return
    pushOlcrtcLine(line)
    // Важные вехи — всегда в UI
    if (/SOCKS5 server listening|using prefetched|telemost:|wbstream:|vp8channel: peer latched|session .+ opened/i.test(line)) {
      log?.(`[olcrtc] ${line.slice(0, 300)}`)
      return
    }
    if (
      /\[ice\] TRACE:|\[sctp\] TRACE:|bufferedAmount|service-unavailable|extdisco|disco_1|\[xmpp|Failed to send packet|unreachable network|wsasendto|Ignore nominate|Failed to ping without candidate pairs|Connection is not possible yet|remote not ready|leave-muc handshake|Failed to accept RTCP|Failed to listen udp|tunnel to dns\.google|tunnel to api2\.cursor\.sh|ICE connection state changed|peer connection state changed|Setting new connection state|bridge open sctp|failed to get server reflexive|failed to allocate on TURN/i.test(
        line,
      )
    ) {
      return
    }
    if (/remote not ready|connect failed/i.test(line)) {
      if (!peerPendingLogged) {
        peerPendingLogged = true
        log?.('[olcrtc] peer dial pending…')
      }
      return
    }
    if (/\bINFO\b|^\d{4}\/\d{2}\/\d{2}/.test(line) && !/\b(ERROR|FATAL|WARN)\b/i.test(line)) {
      log?.(`[olcrtc] ${line.slice(0, 300)}`)
      return
    }
    log?.(`[olcrtc:err] ${line.slice(0, 300)}`)
  })
  olcrtcProc.on('exit', (code) => {
    earlyExitCode = code
    log?.(`[olcrtc] exited code=${code}`)
    const wasReady = ready
    ready = false
    if (sessionActive) {
      sessionActive = false
      killProc(singboxProc, 'sing-box', log)
      singboxProc = null
      if (wasReady || code != null) {
        notifySessionDead(code, 'olcrtc-exit')
      }
    }
  })

  // SOCKS только ПОСЛЕ peer (bringUpLink) — ждём до 90с.
  const socksUp = await waitForPort(socksHost, socksPort, 90_000, log)
  if (!socksUp) {
    const tail = lastOlcrtcLines.slice(-8).join(' | ').slice(0, 400)
    if (tail) log?.(`[olcrtc] last: ${tail}`)
    const hint =
      earlyExitCode != null
        ? `olcrtc вышел с кодом ${earlyExitCode} до SOCKS (peer/room/auth)`
        : `olcrtc SOCKS не поднялся на ${socksHost}:${socksPort} (нет peer srv или ICE в мёртвый TUN — выключите VPN и повторите)`
    stopOlcrtcSession(log)
    return { error: hint }
  }
  log?.(`[olcrtc] SOCKS listen ${socksHost}:${socksPort}`)

  const dialOk = await waitForSocksDial(socksHost, socksPort, 60_000, log, socksUser, socksPass)
  if (!dialOk) {
    stopOlcrtcSession(log)
    return { error: 'olcrtc SOCKS слушает, но peer не отвечает (dial timeout)' }
  }

  singboxProc = spawn(singboxPath, ['run', '-c', sbPath], {
    cwd: path.dirname(singboxPath),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  singboxProc.stdout?.on('data', (buf) => {
    const line = String(buf).trim()
    if (line) log?.(`[sing-box] ${line.slice(0, 200)}`)
  })
  singboxProc.stderr?.on('data', (buf) => {
    const line = String(buf).trim()
    if (!line) return
    if (
      /forcibly closed|wsarecv|listen outbound packet|aborted by the software|connection upload closed|connection download closed|request rejected, code=4|socks5: request rejected|exchange failed for .*\. IN HTTPS|IN HTTPS: EOF|bad rdata|unpack request|process packet connection/i.test(
        line,
      )
    ) {
      return
    }
    log?.(`[sing-box:err] ${line.slice(0, 200)}`)
  })
  singboxProc.on('exit', (code) => {
    log?.(`[sing-box] exited code=${code}`)
  })

  await new Promise((r) => setTimeout(r, 250))
  if (!isOlcrtcAlive()) {
    stopOlcrtcSession(log)
    return { error: 'olcrtc завершился сразу после старта' }
  }

  ready = true
  onReady?.()
  log?.('[olcrtc] session ready (stable dial + warm + TUN)')
  return { success: true }
}

module.exports = {
  beginOlcrtcSession,
  stopOlcrtcSession,
  isOlcrtcSessionActive,
  isOlcrtcAlive,
  findExe,
  setOlcrtcSessionDeadHandler,
}
