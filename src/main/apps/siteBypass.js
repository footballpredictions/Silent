/**
 * Исключения сайтов (домен / IP / CIDR) → host-route через физ. шлюз.
 */
const dns = require('dns').promises
const fs = require('fs')
const path = require('path')
const {
  addServerBypassRoutes,
  removeHostBypassRoutes,
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

let appliedTargets = []
let refreshTimer = null
let lastRulesRaw = ''

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

function saveSiteBypassState(filePath, rules) {
  const capped = parseRules(Array.isArray(rules) ? rules.join('\n') : String(rules || ''))
  const payload = {
    version: 1,
    updatedAt: new Date().toISOString(),
    rules: capped,
  }
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), 'utf8')
  return payload
}

function loadSiteBypassState(filePath) {
  try {
    if (!fs.existsSync(filePath)) return { version: 1, rules: [] }
    const raw = JSON.parse(fs.readFileSync(filePath, 'utf8'))
    return {
      version: raw.version || 1,
      rules: Array.isArray(raw.rules) ? parseRules(raw.rules.join('\n')) : parseRules(raw.raw || ''),
      updatedAt: raw.updatedAt || null,
    }
  } catch {
    return { version: 1, rules: [] }
  }
}

function stopSiteBypassRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

async function clearSiteBypass(send) {
  stopSiteBypassRefresh()
  lastRulesRaw = ''
  if (appliedTargets.length) {
    await removeHostBypassRoutes(appliedTargets, send)
    send?.(`[Sites] снято маршрутов: ${appliedTargets.length}`)
  }
  appliedTargets = []
}

async function applySiteBypass(rules, send) {
  const list = parseRules(Array.isArray(rules) ? rules.join('\n') : String(rules || ''))
  lastRulesRaw = list.join('\n')
  if (!list.length) {
    await clearSiteBypass(send)
    return { ok: true, targets: [], unresolved: [] }
  }
  const { targets, unresolved } = await resolveRulesToTargets(list)
  // Снять старые, которых больше нет
  const nextSet = new Set(targets)
  const toRemove = appliedTargets.filter(t => !nextSet.has(t))
  if (toRemove.length) await removeHostBypassRoutes(toRemove, send)
  const toAdd = targets.filter(t => !appliedTargets.includes(t))
  if (toAdd.length) {
    await addServerBypassRoutes(toAdd, send, { label: 'Sites' })
  }
  appliedTargets = targets
  send?.(`[Sites] обход: ${targets.length} маршрут(ов)${unresolved.length ? `, не резолвится: ${unresolved.slice(0, 3).join(', ')}` : ''}`)

  stopSiteBypassRefresh()
  if (list.some(r => !parseIpOrCidr(r) && domainLookupHosts(r))) {
    refreshTimer = setInterval(() => {
      void applySiteBypass(lastRulesRaw.split('\n'), send)
    }, REFRESH_MS)
    if (typeof refreshTimer.unref === 'function') refreshTimer.unref()
  }
  return { ok: true, targets, unresolved }
}

async function applySiteBypassFromFile(filePath, send) {
  const state = loadSiteBypassState(filePath)
  return applySiteBypass(state.rules, send)
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
}
