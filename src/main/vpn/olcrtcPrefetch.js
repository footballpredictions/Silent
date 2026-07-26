/**
 * Prefetch Telemost / WB auth в Electron (как OkHttp на Android),
 * чтобы Go olcrtc не упирался в TLS/DNS до peer.
 */
const https = require('https')
const http = require('http')
const dns = require('dns').promises
const fs = require('fs')
const path = require('path')
const { randomUUID } = require('crypto')
const { URL } = require('url')

function httpGetJson(urlStr, headers = {}, timeoutMs = 20_000) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr)
    const lib = u.protocol === 'http:' ? http : https
    const req = lib.request(
      {
        protocol: u.protocol,
        hostname: u.hostname,
        port: u.port || (u.protocol === 'http:' ? 80 : 443),
        path: u.pathname + u.search,
        method: 'GET',
        headers,
        timeout: timeoutMs,
      },
      (res) => {
        const chunks = []
        res.on('data', (c) => chunks.push(c))
        res.on('end', () => {
          const body = Buffer.concat(chunks).toString('utf8')
          if (res.statusCode < 200 || res.statusCode >= 300) {
            reject(new Error(`HTTP ${res.statusCode}: ${body.slice(0, 120)}`))
            return
          }
          try {
            resolve(JSON.parse(body))
          } catch (e) {
            reject(e)
          }
        })
      },
    )
    req.on('error', reject)
    req.on('timeout', () => {
      req.destroy()
      reject(new Error('timeout'))
    })
    req.end()
  })
}

function httpPostJson(urlStr, payload, headers = {}, timeoutMs = 20_000) {
  return new Promise((resolve, reject) => {
    const u = new URL(urlStr)
    const body = JSON.stringify(payload)
    const lib = u.protocol === 'http:' ? http : https
    const req = lib.request(
      {
        protocol: u.protocol,
        hostname: u.hostname,
        port: u.port || (u.protocol === 'http:' ? 80 : 443),
        path: u.pathname + u.search,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
          ...headers,
        },
        timeout: timeoutMs,
      },
      (res) => {
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
          } catch {
            resolve({})
          }
        })
      },
    )
    req.on('error', reject)
    req.on('timeout', () => {
      req.destroy()
      reject(new Error('timeout'))
    })
    req.write(body)
    req.end()
  })
}

async function resolveHosts(hosts, into) {
  for (const h of hosts) {
    if (!h || into[h]) continue
    try {
      const r = await dns.lookup(h, { family: 4 })
      if (r?.address) into[h] = r.address
    } catch { /* ignore */ }
  }
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
  const enc = encodeURIComponent(roomUrl)
  const url =
    `https://cloud-api.yandex.ru/telemost_front/v2/telemost/conferences/${enc}/connection` +
    '?next_gen_media_platform_allowed=true&display_name=silent-pc&waiting_room_supported=true'
  const staticHosts = {}
  await resolveHosts(['cloud-api.yandex.ru', 'telemost.yandex.ru', 'goloom.strm.yandex.net'], staticHosts)
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
    const file = path.join(dataDir, 'telemost-conn.json')
    fs.writeFileSync(file, JSON.stringify(info), 'utf8')
    log?.('[olcrtc] Telemost auth prefetch OK')
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
  await resolveHosts(['stream.wb.ru', 'rtc-el-02.wb.ru'], staticHosts)
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
      `https://stream.wb.ru/api-room/api/v1/room/${roomId}/join`,
      {},
      { 'User-Agent': ua, Authorization: `Bearer ${accessToken}` },
    )
    const tok = await httpGetJson(
      `https://stream.wb.ru/api-room-manager/v2/room/${roomId}/connection-details` +
        '?deviceType=PARTICIPANT_DEVICE_TYPE_WEB_DESKTOP&displayName=silent-pc',
      { 'User-Agent': ua, Authorization: `Bearer ${accessToken}` },
    )
    const serverUrl = tok?.serverUrl || 'wss://rtc-el-02.wb.ru'
    const roomToken = tok?.roomToken || ''
    if (!roomToken) {
      log?.('[olcrtc] WB prefetch: пустой roomToken')
      return { staticHosts }
    }
    const h = hostFromUrl(serverUrl)
    if (h) await resolveHosts([h], staticHosts)
    const file = path.join(dataDir, 'wbstream-conn.json')
    fs.writeFileSync(
      file,
      JSON.stringify({ url: serverUrl, token: roomToken, roomID: roomId }),
      'utf8',
    )
    log?.('[olcrtc] WB auth prefetch OK')
    return { connFile: file, staticHosts }
  } catch (e) {
    log?.(`[olcrtc] WB prefetch fail: ${e.message || e}`)
    return { staticHosts }
  }
}

module.exports = {
  prefetchTelemost,
  prefetchWbstream,
}
