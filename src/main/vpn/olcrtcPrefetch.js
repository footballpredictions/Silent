/**
 * Prefetch Telemost / WB auth в Electron (как OkHttp whitelist на Android).
 * Важно: Chromium net / IPv4 — Node https часто таймаутит, если остался WG/TUN.
 */
const https = require('https')
const http = require('http')
const dns = require('dns').promises
const fs = require('fs')
const path = require('path')
const { randomUUID } = require('crypto')
const { URL } = require('url')

async function resolveIpv4(hostname) {
  try {
    const r = await dns.lookup(hostname, { family: 4 })
    return r?.address || ''
  } catch {
    return ''
  }
}

/** Chromium net.fetch (Electron) — ближе к Android OkHttp, чем Node https. */
async function electronFetchJson(urlStr, { method = 'GET', headers = {}, body, timeoutMs = 45_000 } = {}) {
  const { net } = require('electron')
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), timeoutMs)
  try {
    const init = {
      method,
      headers,
      signal: ac.signal,
    }
    if (body != null) {
      init.body = typeof body === 'string' ? body : JSON.stringify(body)
      if (!headers['Content-Type'] && !headers['content-type']) {
        init.headers = { ...headers, 'Content-Type': 'application/json' }
      }
    }
    const res = await net.fetch(urlStr, init)
    const text = await res.text()
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}: ${text.slice(0, 120)}`)
    }
    if (!text) return {}
    try {
      return JSON.parse(text)
    } catch {
      return {}
    }
  } finally {
    clearTimeout(timer)
  }
}

/** Fallback: Node https на IPv4 + SNI (не AAAA Happy Eyeballs). */
function nodeHttpJson(urlStr, { method = 'GET', headers = {}, body, timeoutMs = 45_000, ipv4 } = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr)
    const lib = u.protocol === 'http:' ? http : https
    const payload = body == null ? null : typeof body === 'string' ? body : JSON.stringify(body)
    const hdrs = { ...headers }
    if (payload != null && !hdrs['Content-Type'] && !hdrs['content-type']) {
      hdrs['Content-Type'] = 'application/json'
    }
    if (payload != null) {
      hdrs['Content-Length'] = Buffer.byteLength(payload)
    }
    const opts = {
      protocol: u.protocol,
      hostname: ipv4 || u.hostname,
      servername: u.hostname,
      port: u.port || (u.protocol === 'http:' ? 80 : 443),
      path: u.pathname + u.search,
      method,
      headers: {
        Host: u.hostname,
        ...hdrs,
      },
      timeout: timeoutMs,
      family: 4,
    }
    const req = lib.request(opts, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8')
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode}: ${text.slice(0, 120)}`))
          return
        }
        try {
          resolve(text ? JSON.parse(text) : {})
        } catch (e) {
          reject(e)
        }
      })
    })
    req.on('error', reject)
    req.on('timeout', () => {
      req.destroy()
      reject(new Error('timeout'))
    })
    if (payload != null) req.write(payload)
    req.end()
  })
}

async function httpGetJson(urlStr, headers = {}, timeoutMs = 45_000) {
  try {
    return await electronFetchJson(urlStr, { method: 'GET', headers, timeoutMs })
  } catch (e1) {
    const u = new URL(urlStr)
    const ip = await resolveIpv4(u.hostname)
    try {
      return await nodeHttpJson(urlStr, {
        method: 'GET',
        headers,
        timeoutMs,
        ipv4: ip || undefined,
      })
    } catch (e2) {
      throw new Error(`${e1.message || e1}; fallback: ${e2.message || e2}`)
    }
  }
}

async function httpPostJson(urlStr, payload, headers = {}, timeoutMs = 45_000) {
  try {
    return await electronFetchJson(urlStr, {
      method: 'POST',
      headers,
      body: payload,
      timeoutMs,
    })
  } catch (e1) {
    const u = new URL(urlStr)
    const ip = await resolveIpv4(u.hostname)
    try {
      return await nodeHttpJson(urlStr, {
        method: 'POST',
        headers,
        body: payload,
        timeoutMs,
        ipv4: ip || undefined,
      })
    } catch (e2) {
      throw new Error(`${e1.message || e1}; fallback: ${e2.message || e2}`)
    }
  }
}

async function resolveHosts(hosts, into) {
  const need = (hosts || []).filter((h) => h && !into[h])
  await Promise.all(
    need.map(async (h) => {
      try {
        const r = await dns.lookup(h, { family: 4 })
        if (r?.address) into[h] = r.address
      } catch {
        /* ignore */
      }
    }),
  )
}

function hostFromUrl(urlStr) {
  try {
    return new URL(urlStr).hostname
  } catch {
    return ''
  }
}

async function prefetchTelemost(room, dataDir, log) {
  const roomUrl = room.startsWith('https://') ? room : `https://telemost.yandex.ru/j/${room}`
  const roomIdHint = String(room || '').replace(/^https?:\/\/[^/]+\/j\//, '').split(/[?#]/)[0]
  const file = path.join(dataDir, 'telemost-conn.json')
  const staticHosts = {}
  // Диск-кеш: не бить cloud-api на каждый тумблер (cold start).
  try {
    if (fs.existsSync(file)) {
      const st = fs.statSync(file)
      const ttlMs = 4 * 60 * 1000
      if (Date.now() - st.mtimeMs < ttlMs) {
        const info = JSON.parse(fs.readFileSync(file, 'utf8'))
        const diskRoom = String(info?.room_id || '')
        if (
          diskRoom &&
          (diskRoom === roomIdHint ||
            String(room).includes(diskRoom) ||
            roomUrl.includes(diskRoom))
        ) {
          log?.('[olcrtc] Telemost auth disk hit')
          await resolveHosts(
            [
              'cloud-api.yandex.ru',
              'telemost.yandex.ru',
              'goloom.strm.yandex.net',
              'turn.tel.yandex.net',
              'stun.rtc.yandex.net',
            ],
            staticHosts,
          )
          const media = info?.client_configuration?.media_server_url || ''
          const mediaHost = hostFromUrl(media)
          if (mediaHost) await resolveHosts([mediaHost], staticHosts)
          return { connFile: file, staticHosts }
        }
      }
    }
  } catch {
    /* network path */
  }
  const enc = encodeURIComponent(roomUrl)
  const url =
    `https://cloud-api.yandex.ru/telemost_front/v2/telemost/conferences/${enc}/connection` +
    '?next_gen_media_platform_allowed=true&display_name=silent-pc&waiting_room_supported=true'
  await resolveHosts(
    [
      'cloud-api.yandex.ru',
      'telemost.yandex.ru',
      'goloom.strm.yandex.net',
      'turn.tel.yandex.net',
      'stun.rtc.yandex.net',
    ],
    staticHosts,
  )
  try {
    const info = await httpGetJson(url, {
      'User-Agent':
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
      Accept: '*/*',
      'Content-Type': 'application/json',
      'Client-Instance-Id': randomUUID(),
      'X-Telemost-Client-Version': '187.1.0',
      'Idempotency-Key': randomUUID(),
      Origin: 'https://telemost.yandex.ru',
      Referer: 'https://telemost.yandex.ru/',
    })
    const media = info?.client_configuration?.media_server_url || ''
    if (!info?.room_id || !info?.peer_id || !media) {
      log?.('[olcrtc] Telemost prefetch: нет room_id/peer_id/media')
      return { staticHosts }
    }
    const mediaHost = hostFromUrl(media)
    if (mediaHost) await resolveHosts([mediaHost], staticHosts)
    fs.writeFileSync(file, JSON.stringify(info), 'utf8')
    log?.('[olcrtc] Telemost auth prefetch OK (electron/net)')
    return { connFile: file, staticHosts }
  } catch (e) {
    log?.(`[olcrtc] Telemost prefetch fail: ${e.message || e}`)
    return { staticHosts }
  }
}

async function prefetchWbstream(room, dataDir, log) {
  const roomId = String(room || '')
    .trim()
    .replace(/^https:\/\/stream\.wb\.ru\/room\//, '')
    .replace(/\/$/, '')
  if (!roomId) return {}
  const staticHosts = {}
  await resolveHosts(
    [
      'stream.wb.ru',
      'rtc-el-01.wb.ru',
      'rtc-el-02.wb.ru',
      'stream-meetup.wildberries.ru',
    ],
    staticHosts,
  )
  const ua =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
  try {
    const reg = await httpPostJson(
      'https://stream.wb.ru/auth/api/v1/auth/user/guest-register',
      {
        displayName: 'silent-pc',
        device: {
          deviceName: 'Windows',
          deviceType: 'PARTICIPANT_DEVICE_TYPE_WEB_DESKTOP',
        },
      },
      { 'User-Agent': ua },
    )
    const accessToken = reg?.accessToken || ''
    if (!accessToken) {
      log?.('[olcrtc] WB prefetch: нет accessToken')
      return { staticHosts }
    }
    await httpPostJson(
      `https://stream.wb.ru/api-room/api/v1/room/${encodeURIComponent(roomId)}/join`,
      {},
      { 'User-Agent': ua, Authorization: `Bearer ${accessToken}` },
    )
    const details = await httpGetJson(
      `https://stream.wb.ru/api-room-manager/v2/room/${encodeURIComponent(roomId)}/connection-details?deviceType=PARTICIPANT_DEVICE_TYPE_WEB_DESKTOP&displayName=silent-pc`,
      { 'User-Agent': ua, Authorization: `Bearer ${accessToken}` },
    )
    const serverUrl = details?.serverUrl || details?.url || 'wss://rtc-el-02.wb.ru'
    const roomToken = details?.roomToken || details?.participantToken || details?.token || ''
    if (!serverUrl || !roomToken) {
      log?.('[olcrtc] WB prefetch: нет serverUrl/token')
      return { staticHosts }
    }
    const mediaHost = hostFromUrl(serverUrl)
    if (mediaHost) await resolveHosts([mediaHost], staticHosts)
    const file = path.join(dataDir, 'wbstream-conn.json')
    fs.writeFileSync(
      file,
      JSON.stringify({ url: serverUrl, token: roomToken, roomID: roomId }),
      'utf8',
    )
    log?.('[olcrtc] WB auth prefetch OK (electron/net)')
    return { file, staticHosts }
  } catch (e) {
    const msg = String(e.message || e)
    if (/498/.test(msg)) {
      log?.('[olcrtc] WB prefetch 498 (antibot) — Go guest сам (норма)')
    } else {
      log?.(`[olcrtc] WB prefetch soft-miss: ${msg.slice(0, 160)}`)
    }
    return { staticHosts }
  }
}

module.exports = {
  prefetchTelemost,
  prefetchWbstream,
  resolveHosts,
}
