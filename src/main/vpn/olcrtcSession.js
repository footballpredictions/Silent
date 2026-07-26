/**
 * Debug-only: olcrtc cnc (SOCKS5) + sing-box TUN → SOCKS.
 * Не трогает WDTT/WireGuard.
 */
const { spawn } = require('child_process')
const fs = require('fs')
const path = require('path')
const net = require('net')
const { app } = require('electron')

let olcrtcProc = null
let singboxProc = null
let sessionActive = false
let ready = false

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

/** Один SOCKS5 CONNECT по домену (peer резолвит DNS). */
function socksDialDomainOnce(socksHost, socksPort, domain, timeoutMs = 2500) {
  return new Promise((resolve) => {
    const socket = net.connect({ host: socksHost, port: socksPort }, () => {
      socket.write(Buffer.from([0x05, 0x01, 0x00]))
    })
    let stage = 0
    let buf = Buffer.alloc(0)
    const done = (ok) => {
      socket.destroy()
      resolve(ok)
    }
    socket.on('data', (chunk) => {
      buf = Buffer.concat([buf, chunk])
      if (stage === 0) {
        if (buf.length < 2) return
        if (buf[0] !== 0x05 || buf[1] !== 0x00) return done(false)
        buf = buf.subarray(2)
        stage = 1
        const req = Buffer.alloc(5 + domain.length + 2)
        req[0] = 0x05
        req[1] = 0x01
        req[2] = 0x00
        req[3] = 0x03
        req[4] = domain.length
        req.write(domain, 5)
        req.writeUInt16BE(443, 5 + domain.length)
        socket.write(req)
      } else if (stage === 1) {
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
async function waitForSocksDial(host, port, timeoutMs, log) {
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
    const ok = await socksDialDomainOnce(host, port, probeHost, 2800)
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
    log?.(`[olcrtc] SOCKS dial OK ×2 → ${probeHost}:443`)
    // Прогрев DNS на peer (не блокируем ready дольше ~1с)
    await Promise.race([
      Promise.allSettled(warmHosts.map((d) => socksDialDomainOnce(host, port, d, 2000))),
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
    require('child_process').execSync('taskkill /F /IM olcrtc.exe /T', {
      stdio: 'ignore',
      windowsHide: true,
    })
  } catch { /* ignore */ }
  try {
    require('child_process').execSync('taskkill /F /IM sing-box.exe /T', {
      stdio: 'ignore',
      windowsHide: true,
    })
  } catch { /* ignore */ }
  log?.('[olcrtc] session stopped')
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
  const transport = String(config.olcrtc_transport || config.olcrtcTransport || 'datachannel').trim()
  const socksHost = String(config.olcrtc_socks_host || '127.0.0.1')
  const socksPort = Number(config.olcrtc_socks_port || 8808)
  const authToken = String(config.olcrtc_auth_token || config.olcrtcAuthToken || '').trim()
  if (!room || key.length !== 64) {
    throw new Error('olcrtc: нужны room и crypto_key (64 hex) из /api/vpn/olcrtc-config')
  }
  const authLines = ['auth:', `  provider: ${provider}`]
  if (authToken) {
    const esc = authToken.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
    authLines.push(`  token: "${esc}"`)
  }
  return [
    'mode: cnc',
    ...authLines,
    'room:',
    `  id: "${room}"`,
    'crypto:',
    `  key: "${key}"`,
    'net:',
    `  transport: ${transport}`,
    '  dns: "8.8.8.8:53"',
    'socks:',
    `  host: "${socksHost}"`,
    `  port: ${socksPort}`,
    'data: data',
    '',
  ].join('\n')
}

function renderSingboxConfig(socksHost, socksPort) {
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
  stopOlcrtcSession(log)
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
  // Absolute data path; без debug:true — меньше ICE/XMPP TRACE в лог.
  yaml = yaml.replace(/\ndata: data\n/, `\ndata: "${dataDir.replace(/\\/g, '/')}"\n`)
  fs.writeFileSync(yamlPath, yaml, 'utf8')
  fs.writeFileSync(sbPath, renderSingboxConfig(socksHost, socksPort), 'utf8')

  sessionActive = true
  ready = false
  log?.(`[olcrtc] start ${olcrtcPath}`)
  log?.(`[olcrtc] provider=${config.olcrtc_provider || 'telemost'} room=${String(config.olcrtc_room || '').slice(0, 60)} yaml=${yamlPath}`)

  olcrtcProc = spawn(olcrtcPath, [yamlPath], {
    cwd: dataDir,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let earlyExitCode = null
  let peerPendingLogged = false
  olcrtcProc.stdout?.on('data', (buf) => {
    const line = String(buf).trim()
    if (!line) return
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
    if (
      /\[ice\] TRACE:|\[sctp\] TRACE:|bufferedAmount|service-unavailable|extdisco|disco_1|\[xmpp|Failed to send packet|unreachable network|wsasendto|Ignore nominate|Failed to ping without candidate pairs|Connection is not possible yet|remote not ready|leave-muc handshake|Failed to accept RTCP|Failed to listen udp|tunnel to dns\.google|tunnel to api2\.cursor\.sh|ICE connection state changed|peer connection state changed|Setting new connection state|bridge open sctp|session .+ opened|SOCKS5 server listening/i.test(
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
    // olcrtc пишет INFO в stderr — не помечать как :err
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

  // SOCKS поднимается раньше peer; dial-probe ждёт реальную готовность (без долгого «прогрева» после ready).
  const socksUp = await waitForPort(socksHost, socksPort, 90_000, log)
  if (!socksUp) {
    const hint =
      earlyExitCode != null
        ? `olcrtc вышел с кодом ${earlyExitCode} до SOCKS (нет peer/room/key или Jitsi недоступен)`
        : `olcrtc SOCKS не поднялся на ${socksHost}:${socksPort} (ждём peer srv в комнате)`
    stopOlcrtcSession(log)
    return { error: hint }
  }
  log?.(`[olcrtc] SOCKS listen ${socksHost}:${socksPort}`)

  const dialOk = await waitForSocksDial(socksHost, socksPort, 60_000, log)
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
