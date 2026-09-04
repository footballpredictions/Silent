/**
 * IP VK login/api — вне AllowedIPs WG (как Android VkNetworkExcludes).
 * Только критичные хосты — укладываемся в лимит маршрутов Windows (32).
 */
const dns = require('dns').promises

const VK_HOSTS = [
  'api.vk.ru',
  'api.vk.com',
  'api.vk.me',
  'login.vk.ru',
  'login.vk.com',
  'id.vk.ru',
  'oauth.vk.ru',
  'oauth.vk.com',
  // VK Calls step4+ (auth.anonymLogin / join) — без bypass на Linux dialViaLan → timeout.
  'calls.okcdn.ru',
  'okcdn.ru',
  'stun.vk.com',
  'turn.vk.com',
  'vk.ru',
  'vk.com',
]

const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/

let cachedIps = null
/** @type {Record<string, string[]> | null} */
let cachedHostMap = null
let cacheAt = 0
const CACHE_MS = 5 * 60 * 1000

function invalidateVkExcludeCache() {
  cachedIps = null
  cachedHostMap = null
  cacheAt = 0
}

async function resolveVkExcludeHostMap() {
  const now = Date.now()
  if (cachedHostMap && now - cacheAt < CACHE_MS) return cachedHostMap

  /** @type {Record<string, string[]>} */
  const map = {}
  await Promise.all(
    VK_HOSTS.map(async (host) => {
      try {
        const addrs = await dns.resolve4(host)
        map[host] = addrs.filter((ip) => IPV4.test(ip))
      } catch {
        map[host] = []
      }
    }),
  )
  const out = new Set()
  for (const ips of Object.values(map)) {
    for (const ip of ips) out.add(ip)
  }
  cachedHostMap = map
  cachedIps = [...out]
  cacheAt = now
  return map
}

async function resolveVkExcludeIps() {
  const now = Date.now()
  if (cachedIps && now - cacheAt < CACHE_MS) return cachedIps
  await resolveVkExcludeHostMap()
  return cachedIps || []
}

/** Прогрев DNS при старте приложения — connect не ждёт resolve. */
function warmVkExcludeIps() {
  void resolveVkExcludeHostMap()
}

/** Пары ip:hostname для Linux /etc/hosts (WDTT auth без живого DNS). */
function hostPinPairsFromMap(hostMap) {
  const pairs = []
  if (!hostMap || typeof hostMap !== 'object') return pairs
  for (const [host, ips] of Object.entries(hostMap)) {
    if (!host || !Array.isArray(ips)) continue
    for (const ip of ips) {
      if (IPV4.test(ip)) pairs.push(`${ip}:${host}`)
    }
  }
  return pairs
}

module.exports = {
  resolveVkExcludeIps,
  resolveVkExcludeHostMap,
  hostPinPairsFromMap,
  warmVkExcludeIps,
  invalidateVkExcludeCache,
  VK_HOSTS,
}
