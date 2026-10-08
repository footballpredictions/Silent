/**
 * Исключения сайтов (домен / IP / CIDR). Windows: политика процессов браузера.
 * Linux/macOS пока используют прежние host-route через физический шлюз.
 */
const dns = require('dns').promises
const fs = require('fs')
const path = require('path')
const { siteDirectTargets } = require('./siteRoutingPolicy')
const { browserDomains, browserLookupHosts } = require('./siteServiceDomains')
const {
  addServerBypassRoutes,
  removeHostBypassRoutes,
  capturePhysicalGateway,
} = require('../vpn/wireguard')
const {
  MAX_RULES,
  normalizeRuleInput,
  extractRulesFromImportContent,
  mergeImportRules,
} = require('./siteImportParse')

const IPV4_RE = /^\d{1,3}(?:\.\d{1,3}){3}$/
const CIDR_RE = /^\d{1,3}(?:\.\d{1,3}){3}\/\d{1,2}$/
const REFRESH_MS = 20 * 60 * 1000
const browserDnsCache = new Map()

let appliedTargets = []
let refreshTimer = null
let lastRulesRaw = ''
let lastOptions = {}
let operations = Promise.resolve()
let routingGeneration = 0
let appliedGateway = null
function serialize(operation) {
  const result = operations.then(operation)
  operations = result.catch(() => {})
  return result
}

function defaultSiteBypassPath(userDataPath) {
  return path.join(userDataPath, 'site-bypass.json')
}

function parseRules(raw) {
  return String(raw || '')
    .split(/\r?\n/)
    .map(l => l.replace(/#.*$/, '').trim())
    .map(normalizeRuleInput)
    .filter(Boolean)
    .filter((v, i, a) => a.findIndex(x => x.toLowerCase() === v.toLowerCase()) === i)
    .slice(0, MAX_RULES)
}

function isDomainName(host) {
  if (!host || host.length > 253 || !host.includes('.')) return false
  if (host.startsWith('.') || host.endsWith('.') || host.includes('..')) return false
  const labels = host.toLowerCase().split('.')
  if (labels.some(l => !l || l.length > 63 || !/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(l))) return false
  return /[a-z]/i.test(labels[labels.length - 1])
}

function parseIpOrCidr(rule) {
  if (CIDR_RE.test(rule)) {
    const [ip, p] = rule.split('/')
    const prefix = Number(p)
    if (!IPV4_RE.test(ip) || prefix < 0 || prefix > 32) return null
    return rule
  }
  if (IPV4_RE.test(rule)) return `${rule}/32`
  // wildcard 1.2.*.*
  const parts = rule.split('.')
  if (parts.length === 4 && parts.includes('*')) {
    let prefix = 0
    let seenStar = false
    const nums = []
    for (let i = 0; i < 4; i++) {
      if (parts[i] === '*') {
        seenStar = true
        nums.push(0)
        continue
      }
      if (seenStar) return null
      const o = Number(parts[i])
      if (!Number.isInteger(o) || o < 0 || o > 255) return null
      nums.push(o)
      prefix = (i + 1) * 8
    }
    return `${nums.join('.')}/${prefix}`
  }
  return null
}

function domainLookupHosts(rule) {
  let host = normalizeRuleInput(rule).toLowerCase()
  if (host.startsWith('*.')) {
    host = host.slice(2)
    if (!isDomainName(host)) return null
    return [host, `www.${host}`]
  }
  if (!isDomainName(host)) return null
  return [host]
}

async function resolveHosts(hosts) {
  const out = new Set()
  for (const host of hosts) {
    try {
      const addrs = await dns.resolve4(host)
      for (const a of addrs) {
        if (IPV4_RE.test(a)) out.add(`${a}/32`)
      }
    } catch {
      try {
        const all = await dns.lookup(host, { all: true, family: 4 })
        for (const a of all) {
          if (a?.address && IPV4_RE.test(a.address)) out.add(`${a.address}/32`)
        }
      } catch { /* ignore */ }
    }
  }
  return [...out]
}

async function resolveRulesToTargets(rules) {
  const targets = new Set()
  const unresolved = []
  for (const rule of rules) {
    const cidr = parseIpOrCidr(rule)
    if (cidr) {
      targets.add(cidr)
      continue
    }
    const hosts = domainLookupHosts(rule)
    if (!hosts) {
      unresolved.push(rule)
      continue
    }
    const ips = await resolveHosts(hosts)
    if (!ips.length) unresolved.push(rule)
    else ips.forEach(t => targets.add(t))
  }
  return { targets: [...targets], unresolved }
}

function initialBrowserPolicy(rules, whitelist) {
  const domains = browserDomains(rules.filter(rule => domainLookupHosts(rule)))
  return {
    whitelist: whitelist === true,
    targets: [...new Set(rules.map(parseIpOrCidr).filter(Boolean))],
    domains,
    pendingDNS: domains.length > 0,
  }
}

// Native browser routing learns real in-tunnel DNS. The fallback snapshot must
// not block policy edits/disconnect when the system resolver is unreachable.
async function resolveBrowserRulesToTargets(rules, { timeoutMs = 2000, dnsServers = [] } = {}) {
  const policy = initialBrowserPolicy(rules, false)
  const targets = new Set(policy.targets)
  const unresolved = []
  const resolver = new dns.Resolver({ timeout: Math.min(750, timeoutMs), tries: 1 })
  // Electron may have initialized DNS before the VPN existed. Use the tunnel's
  // configured resolvers explicitly, rather than an old LAN-only DNS address.
  if (dnsServers.length) resolver.setServers(dnsServers)
  const deadline = Date.now() + timeoutMs
  const selected = new Set(rules)
  const domainRules = rules.filter(rule => domainLookupHosts(rule))
  for (const [rule, entry] of browserDnsCache) {
    if (!selected.has(rule) || entry.expires <= Date.now()) browserDnsCache.delete(rule)
  }
  let cursor = 0
  let expired = false
  const timer = setTimeout(() => { expired = true; resolver.cancel() }, timeoutMs)
  const worker = async () => {
    while (cursor < domainRules.length) {
      const rule = domainRules[cursor++]
      const hosts = browserLookupHosts(rule, domainLookupHosts(rule))
      let ips = []
      if (!expired && Date.now() < deadline) {
        const answers = await Promise.all(hosts.map(host => resolver.resolve4(host).catch(() => [])))
        ips = [...new Set(answers.flat().filter(ip => IPV4_RE.test(ip)).map(ip => `${ip}/32`))]
      }
      if (ips.length) browserDnsCache.set(rule, { ips, expires: Date.now() + 5 * 60 * 1000 })
      else ips = browserDnsCache.get(rule)?.ips || []
      if (!ips.length) unresolved.push(rule)
      for (const ip of ips) targets.add(ip)
    }
  }
  try {
    await Promise.all(Array.from({ length: Math.min(8, domainRules.length) }, worker))
  } finally {
    clearTimeout(timer)
    resolver.cancel()
  }
  return { targets: [...targets], unresolved }
}

function saveSiteBypassState(filePath, rules, whitelist = loadSiteBypassState(filePath).whitelist) {
  const capped = parseRules(Array.isArray(rules) ? rules.join('\n') : String(rules || ''))
  const payload = {
    version: 1,
    updatedAt: new Date().toISOString(),
    rules: capped,
    whitelist: whitelist === true,
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), 'utf8')
  return payload
}

function loadSiteBypassState(filePath) {
  try {
    if (!fs.existsSync(filePath)) return { version: 1, rules: [], whitelist: false }
    const raw = JSON.parse(fs.readFileSync(filePath, 'utf8'))
    return {
      version: raw.version || 1,
      whitelist: raw.whitelist === true,
      rules: Array.isArray(raw.rules) ? parseRules(raw.rules.join('\n')) : parseRules(raw.raw || ''),
      updatedAt: raw.updatedAt || null,
    }
  } catch {
    return { version: 1, rules: [], whitelist: false }
  }
}

function stopSiteBypassRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

async function clearSiteBypassUnlocked(send) {
  stopSiteBypassRefresh()
  lastRulesRaw = ''
  if (appliedTargets.length) {
    await removeHostBypassRoutes(appliedTargets, send, null, { physicalOnly: true, gateway: appliedGateway })
    send?.(`[Sites] снято маршрутов: ${appliedTargets.length}`)
  }
  appliedTargets = []
  appliedGateway = null
  if (process.platform === 'win32') {
    await require('../vpn/browserRouter').updatePolicy({ whitelist: false, targets: [], domains: [], pendingDNS: false })
  }
}

function clearSiteBypass(send) {
  routingGeneration++
  stopSiteBypassRefresh()
  return serialize(() => clearSiteBypassUnlocked(send))
}

function applySiteBypass(rules, send, options = {}) {
  const generation = routingGeneration
  return serialize(() => applySiteBypassUnlocked(rules, send, options, generation))
}

async function applySiteBypassUnlocked(rules, send, options, generation) {
  if (generation !== routingGeneration) return { ok: false, cancelled: true }
  const list = parseRules(Array.isArray(rules) ? rules.join('\n') : String(rules || ''))
  if (!list.length && !options.whitelist) {
    await clearSiteBypassUnlocked(send)
    return { ok: true, targets: [], unresolved: [] }
  }
  const browserOnly = options.browserOnly || process.platform === 'win32'
  const resolved = browserOnly ? await resolveBrowserRulesToTargets(list, { dnsServers: options.dnsServers }) : await resolveRulesToTargets(list)
  if (generation !== routingGeneration) return { ok: false, cancelled: true }
  const { unresolved } = resolved
  if (browserOnly) {
    const domains = browserDomains(list.filter(rule => domainLookupHosts(rule)))
    await require('../vpn/browserRouter').updatePolicy({ whitelist: options.whitelist === true, targets: resolved.targets, domains, pendingDNS: unresolved.length > 0 })
    lastRulesRaw = list.join('\n')
    lastOptions = options
    stopSiteBypassRefresh()
    // Actual DNS answers in the router learn subdomains/TTL. Refresh the snapshot
    // as a fallback for browsers with their own encrypted resolver.
    if (generation === routingGeneration && domains.length) {
      refreshTimer = setInterval(() => { void applySiteBypass(lastRulesRaw.split('\n'), send, lastOptions).catch(e => send?.(`[Sites] ${e.message}`)) }, unresolved.length ? 15000 : REFRESH_MS)
      refreshTimer.unref?.()
    }
    send?.(`[Sites] правила браузеров применены: ${options.whitelist ? 'БС' : 'ЧС'}, доменов=${domains.length}, IP=${resolved.targets.length}, без DNS=${unresolved.length}`)
    return { ok: true, targets: resolved.targets, unresolved }
  }
  const targets = siteDirectTargets(resolved.targets, options.whitelist, options.dnsServers)
  const previousTargets = appliedTargets
  // Снять старые, которых больше нет
  const nextSet = new Set(targets)
  const toRemove = appliedTargets.filter(t => !nextSet.has(t))
  if (toRemove.length) await removeHostBypassRoutes(toRemove, send, null, { physicalOnly: true, gateway: appliedGateway })
  const toAdd = targets.filter(t => !appliedTargets.includes(t))
  if (!appliedGateway) appliedGateway = await capturePhysicalGateway(send)
  if (generation !== routingGeneration) return { ok: false, cancelled: true }
  // Track attempted additions too, so disconnect cleans up a partially failed batch.
  appliedTargets = targets
  if (toAdd.length) {
    const ok = await addServerBypassRoutes(toAdd, send, { label: 'Sites', requireAll: true })
    if (!ok) {
      await removeHostBypassRoutes(toAdd, send, null, { physicalOnly: true, gateway: appliedGateway })
      if (toRemove.length) await addServerBypassRoutes(toRemove, send, { label: 'Sites', requireAll: true })
      appliedTargets = previousTargets
      throw new Error('Не удалось применить маршруты сайтов')
    }
  }
  send?.(`[Sites] обход: ${targets.length} маршрут(ов)${unresolved.length ? `, не резолвится: ${unresolved.slice(0, 3).join(', ')}` : ''}`)

  lastRulesRaw = list.join('\n')
  lastOptions = options
  stopSiteBypassRefresh()
  if (generation === routingGeneration && list.some(r => !parseIpOrCidr(r) && domainLookupHosts(r))) {
    refreshTimer = setInterval(() => {
      void applySiteBypass(lastRulesRaw.split('\n'), send, lastOptions).catch(e => send?.(`[Sites] ${e.message}`))
    }, REFRESH_MS)
    if (typeof refreshTimer.unref === 'function') refreshTimer.unref()
  }
  return { ok: true, targets, unresolved }
}

async function applySiteBypassFromFile(filePath, send, options = {}) {
  const state = loadSiteBypassState(filePath)
  return applySiteBypass(state.rules, send, { ...options, whitelist: state.whitelist })
}

module.exports = {
  MAX_RULES,
  normalizeRuleInput,
  parseRules,
  extractRulesFromImportContent,
  mergeImportRules,
  defaultSiteBypassPath,
  saveSiteBypassState,
  loadSiteBypassState,
  applySiteBypass,
  applySiteBypassFromFile,
  clearSiteBypass,
  resolveRulesToTargets,
  domainLookupHosts,
  initialBrowserPolicy,
  resolveBrowserRulesToTargets,
}
