/**
 * Парсер импорта списков сайтов (json / txt / csv / смешанный текст).
 * ESM-копия для Vite renderer; логика = main/apps/siteImportParse.js.
 */

export const MAX_RULES = 100
const IPV4_RE = /^\d{1,3}(?:\.\d{1,3}){3}$/
const CIDR_RE = /^\d{1,3}(?:\.\d{1,3}){3}\/\d{1,2}$/

const IMPORT_DOMAIN_RE =
  /(?:\*\.|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}/gi
const IMPORT_IPV4_RE =
  /\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?:\/(?:3[0-2]|[12]?\d))?\b/g
const IMPORT_IPV6_RE = /\b(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?:\/\d{1,3})?\b/gi
const IMPORT_URL_RE = /https?:\/\/[^\s/]+[^\s]*/gi

const JSON_META_KEYS = new Set(['version', 'schema', 'updated', 'updatedat', 'updated_at', 'comment'])
const JSON_CONTAINER_KEYS = [
  'rules', 'sites', 'domains', 'hosts', 'items', 'data', 'list', 'entries',
  'config', 'payload', 'body', 'result',
]

function stripQuotes(raw: string): string {
  return String(raw || '').trim().replace(/^["']+|["']+$/g, '')
}

export function normalizeRuleInput(raw: string): string {
  let s = String(raw || '').trim()
  if (!s) return ''
  if (/^https?:\/\//i.test(s)) {
    try {
      s = new URL(s).hostname || s
    } catch { /* keep */ }
  } else if (s.includes('/') && !CIDR_RE.test(s)) {
    const before = s.split('/')[0]
    if (!IPV4_RE.test(before)) s = before
  }
  return s.trim().replace(/\.$/, '')
}

function looksLikeRule(raw: string): boolean {
  const n = normalizeRuleInput(stripQuotes(raw))
  if (!n) return false
  if (/\d+\.\d+\.\d+\.\d+/.test(n)) return true
  if (n.includes(':')) return true
  return /^[a-z0-9*](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/i.test(n)
}

function walkJsonNode(node: unknown, addRaw: (raw: string) => void) {
  if (node == null) return
  if (typeof node === 'string') {
    addRaw(node)
    return
  }
  if (Array.isArray(node)) {
    for (const child of node) walkJsonNode(child, addRaw)
    return
  }
  if (typeof node === 'object') {
    const obj = node as Record<string, unknown>
    for (const key of JSON_CONTAINER_KEYS) {
      if (JSON_META_KEYS.has(String(key).toLowerCase())) continue
      if (!(key in obj)) continue
      const child = obj[key]
      if (Array.isArray(child) || (child && typeof child === 'object')) walkJsonNode(child, addRaw)
      else if (typeof child === 'string') addRaw(child)
    }
  }
}

function tryParseJsonRoot(text: string): unknown {
  const trimmed = String(text || '').trim()
  if (!trimmed) return null
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      return JSON.parse(trimmed)
    } catch { /* fall through */ }
  }
  const objStart = trimmed.indexOf('{')
  const objEnd = trimmed.lastIndexOf('}')
  if (objStart >= 0 && objEnd > objStart) {
    try {
      return JSON.parse(trimmed.slice(objStart, objEnd + 1))
    } catch { /* ignore */ }
  }
  const arrStart = trimmed.indexOf('[')
  const arrEnd = trimmed.lastIndexOf(']')
  if (arrStart >= 0 && arrEnd > arrStart) {
    try {
      return JSON.parse(trimmed.slice(arrStart, arrEnd + 1))
    } catch { /* ignore */ }
  }
  return null
}

function extractFromPlainText(text: string, addRaw: (raw: string) => void) {
  try {
    const parsed = tryParseJsonRoot(text)
    if (parsed != null) walkJsonNode(parsed, addRaw)
  } catch { /* ignore */ }

  const urls = text.match(IMPORT_URL_RE) || []
  for (const u of urls) addRaw(u)
  const ipv4 = text.match(IMPORT_IPV4_RE) || []
  for (const ip of ipv4) addRaw(ip)
  const ipv6 = text.match(IMPORT_IPV6_RE) || []
  for (const ip of ipv6) addRaw(ip)
  const domains = text.match(IMPORT_DOMAIN_RE) || []
  for (const d of domains) addRaw(d)

  for (const line of String(text || '').split(/\r?\n/)) {
    const l = line.replace(/#.*$/, '').trim()
    if (!l) continue
    if (l.includes('{') || l.includes('[')) continue
    if (l.includes(',') && !l.includes('://')) {
      for (const part of l.split(',')) {
        if (looksLikeRule(part)) addRaw(part)
      }
    } else if (looksLikeRule(l)) {
      addRaw(l)
    }
  }
}

/** Извлекает домены / IPv4 / IPv6 из json, txt, csv и смешанного текста. */
export function extractRulesFromImportContent(content: string): string[] {
  const found = new Map<string, string>()
  const addRaw = (raw: string) => {
    const n = normalizeRuleInput(stripQuotes(raw))
    if (!n) return
    const key = n.toLowerCase()
    if (!found.has(key)) found.set(key, n)
  }

  const text = String(content || '')
  const trimmed = text.trim()
  let jsonHandled = false
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const node = JSON.parse(trimmed)
      walkJsonNode(node, addRaw)
      jsonHandled = true
    } catch {
      jsonHandled = false
    }
  }

  if (!jsonHandled || found.size === 0) {
    extractFromPlainText(text, addRaw)
  }

  return [...found.values()]
}

/** Merge: уникальные правила, не выше maxRules. */
export function mergeImportRules(
  existing: string[],
  imported: string[],
  maxRules = MAX_RULES,
): string[] {
  const seen = new Set((existing || []).map(r => String(r).toLowerCase()))
  const out = [...(existing || [])]
  for (const raw of imported || []) {
    const n = normalizeRuleInput(raw)
    if (!n) continue
    const key = n.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    out.push(n)
    if (out.length >= maxRules) break
  }
  return out
}
