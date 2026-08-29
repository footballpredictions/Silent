/**
 * Префиксные bypass-наборы для известных платформ.
 * Включаются только если соответствующий .exe выбран в исключениях —
 * механизм общий для любого пункта меню, не «только Dota».
 */
const https = require('https')
const path = require('path')

/** Valve / Steam (AS32590 и CDN) — нужно до первого UDP ping в играх */
const STEAM_VALVE_CIDRS = [
  '155.133.224.0/19',
  '155.133.248.0/21',
  '162.254.192.0/18',
  '146.66.152.0/21',
  '146.66.155.0/24',
  '185.25.180.0/22',
  '190.216.120.0/22',
  '190.217.32.0/22',
  '192.69.96.0/19',
  '205.185.194.0/24',
  '205.196.6.0/24',
  '208.64.200.0/22',
  '208.78.164.0/22',
  '45.121.184.0/22',
  '103.10.124.0/23',
  '103.28.54.0/23',
  '153.254.86.0/23',
  '61.97.32.0/20', // steam APAC CDN
]

const EPIC_HOSTS = [
  'epicgames.com',
  'unrealengine.com',
  'ol.epicgames.com',
  'account-public-service-prod.ol.epicgames.com',
]

const DISCORD_HOSTS = [
  'discord.com',
  'discord.gg',
  'discordapp.com',
  'discord.media',
  'gateway.discord.gg',
]

const ROBLOX_HOSTS = [
  'roblox.com',
  'rbxcdn.com',
  'roblox.cn',
]

const BLUESTACKS_HOSTS = [
  'bluestacks.com',
  'bstopsvn.com',
  'cloud.bluestacks.com',
]

/**
 * @typedef {{ id: string, match: (exe: string, leaf: string) => boolean, cidrs?: string[], hosts?: string[], sdrAppIds?: number[] }} Pack
 */

/** @type {Pack[]} */
const PACKS = [
  {
    id: 'steam',
    match: (exe, leaf) =>
      leaf === 'steam.exe'
      || leaf === 'steam'
      || leaf === 'steamwebhelper.exe'
      || leaf === 'steamservice.exe'
      || leaf === 'dota2.exe'
      || leaf === 'dota2'
      || leaf === 'cs2.exe'
      || leaf === 'cs2'
      || leaf === 'csgo.exe'
      || exe.includes('\\steam\\')
      || exe.includes('\\steamapps\\'),
    cidrs: STEAM_VALVE_CIDRS,
    hosts: [
      'steamcommunity.com',
      'steampowered.com',
      'steamgames.com',
      'steamusercontent.com',
      'steamcontent.com',
      'steamstatic.com',
      'steamserver.net',
      'api.steampowered.com',
      'store.steampowered.com',
      'cm.steampowered.com',
    ],
    // Live SDR pops (Valve + partners) — иначе «не удалось вычислить задержку»
    sdrAppIds: [570, 730],
  },
  {
    id: 'epic',
    match: (exe, leaf) =>
      leaf.includes('epicgames')
      || leaf === 'fortniteclient-win64-shipping.exe'
      || exe.includes('\\epic games\\'),
    hosts: EPIC_HOSTS,
  },
  {
    id: 'discord',
    match: (exe, leaf) =>
      leaf === 'discord.exe'
      || leaf === 'discord'
      || exe.includes('\\discord\\')
      || exe.includes('\\discord'),
    hosts: DISCORD_HOSTS,
  },
  {
    id: 'roblox',
    match: (exe, leaf) => leaf.startsWith('roblox') || exe.includes('\\roblox\\'),
    hosts: ROBLOX_HOSTS,
  },
  {
    id: 'bluestacks',
    match: (exe, leaf) =>
      leaf === 'hd-player.exe'
      || leaf.includes('bluestacks')
      || exe.includes('\\bluestacks'),
    hosts: BLUESTACKS_HOSTS,
  },
]

function packsForExePaths(exePaths) {
  const matched = new Set()
  const cidrs = new Set()
  const hosts = new Set()
  const sdrAppIds = new Set()
  for (const raw of exePaths || []) {
    const exe = String(raw || '').replace(/\//g, '\\').toLowerCase()
    if (!exe) continue
    const leaf = path.basename(exe)
    for (const pack of PACKS) {
      if (!pack.match(exe, leaf)) continue
      matched.add(pack.id)
      for (const c of pack.cidrs || []) cidrs.add(c)
      for (const h of pack.hosts || []) hosts.add(h)
      for (const id of pack.sdrAppIds || []) sdrAppIds.add(id)
    }
  }
  return {
    packIds: [...matched],
    cidrs: [...cidrs],
    hosts: [...hosts],
    sdrAppIds: [...sdrAppIds],
  }
}

function httpsGetJson(url, timeoutMs = 12000) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { timeout: timeoutMs }, (res) => {
      if (res.statusCode && res.statusCode >= 400) {
        res.resume()
        reject(new Error(`HTTP ${res.statusCode}`))
        return
      }
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => {
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')))
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
  })
}

/**
 * Актуальные /24 релеев Steam Datagram (включая партнёров PoP).
 * Без этого Dota считает задержку через VPN и пишет «проверьте интернет».
 */
async function fetchSteamSdrCidrs(appIds = [570, 730]) {
  const cidrs = new Set()
  await Promise.all(
    (appIds || []).map(async (appid) => {
      try {
        const data = await httpsGetJson(
          `https://api.steampowered.com/ISteamApps/GetSDRConfig/v1?appid=${appid}`,
        )
        for (const pop of Object.values(data?.pops || {})) {
          for (const r of pop?.relays || []) {
            const ip = String(r?.ipv4 || '')
            if (!/^\d{1,3}(?:\.\d{1,3}){3}$/.test(ip)) continue
            const p = ip.split('.')
            cidrs.add(`${p[0]}.${p[1]}.${p[2]}.0/24`)
          }
        }
      } catch {
        /* offline / blocked — остаёмся на статическом Valve CIDR */
      }
    }),
  )
  return [...cidrs]
}

module.exports = {
  packsForExePaths,
  fetchSteamSdrCidrs,
  PACKS,
  STEAM_VALVE_CIDRS,
}
