export interface HashItem {
  hash: string
  label: string
  source: string
  slot_index?: number | null
  is_active: boolean
  status: string
}

const ITEMS_KEY = 'silent_saved_hash_items'
const TS_KEY = 'silent_saved_hash_items_ts'

export const MAX_SERVER_HASHES = 4

export function getSavedHashItems(): HashItem[] {
  try {
    const raw = localStorage.getItem(ITEMS_KEY)
    const items = raw ? (JSON.parse(raw) as HashItem[]) : []
    return items.filter(i => i.source !== 'bootstrap')
  } catch {
    return []
  }
}

export function getSavedHashItemsUpdatedAt(): number {
  const n = Number(localStorage.getItem(TS_KEY) || 0)
  return Number.isFinite(n) ? n : 0
}

export function saveHashItems(items: HashItem[]): void {
  const serverOnly = items.filter(i => i.source !== 'bootstrap' && i.hash?.trim())
  localStorage.setItem(ITEMS_KEY, JSON.stringify(serverOnly))
  localStorage.setItem(TS_KEY, String(Date.now()))
}

export function clearSavedHashItems(): void {
  localStorage.removeItem(ITEMS_KEY)
  localStorage.removeItem(TS_KEY)
}

export function formatSavedAt(ts: number): string {
  if (!ts) return ''
  return new Date(ts).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function activeServerHashes(items: HashItem[]): HashItem[] {
  return items.filter(
    i => i.source !== 'bootstrap' && i.is_active && i.status === 'active' && i.hash?.trim(),
  )
}

export function activeServerHashCount(items: HashItem[]): number {
  return Math.min(activeServerHashes(items).length, MAX_SERVER_HASHES)
}

export function mapHashesResponse(body: {
  items?: HashItem[]
  hashes?: string[]
  bootstrap_hash?: string
}): HashItem[] {
  if (body.items?.length) {
    return body.items.filter(i => i.source !== 'bootstrap' && i.hash?.trim())
  }
  const boot = (body.bootstrap_hash || '').trim()
  const hashes: string[] = body.hashes || []
  return hashes
    .filter(h => h?.trim() && h !== boot)
    .map((h, i) => ({
      hash: h,
      label: `Сервер #${i}`,
      source: 'server',
      slot_index: i,
      is_active: true,
      status: 'active',
    }))
}
