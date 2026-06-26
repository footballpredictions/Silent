/**
 * IP VK login/api — вне AllowedIPs WG (как Android VkNetworkExcludes).
 * Только критичные хосты — укладываемся в лимит маршрутов Windows (32).
 */
const dns = require('dns').promises

const VK_HOSTS = [
  'api.vk.ru',
  'api.vk.com',
  'login.vk.ru',
  'login.vk.com',
  'id.vk.ru',
  'oauth.vk.ru',
  'oauth.vk.com',
  'stun.vk.com',
  'turn.vk.com',
  'vk.ru',
  'vk.com',
]

const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/

let cachedIps = null
let cacheAt = 0
const CACHE_MS = 5 * 60 * 1000

async function resolveVkExcludeIps() {
  const now = Date.now()
  if (cachedIps && now - cacheAt < CACHE_MS) return cachedIps

  const out = new Set()
  for (const host of VK_HOSTS) {
    try {
      const addrs = await dns.resolve4(host)
      for (const ip of addrs) {
        if (IPV4.test(ip)) out.add(ip)
      }
    } catch {
      /* ignore */
    }
  }
  cachedIps = [...out]
  cacheAt = now
  return cachedIps
}

module.exports = { resolveVkExcludeIps, VK_HOSTS }
