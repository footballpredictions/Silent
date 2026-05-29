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

export function getSavedHashItems(): HashItem[] {
  try {
    const raw = localStorage.getItem(ITEMS_KEY)
    return raw ? (JSON.parse(raw) as HashItem[]) : []
  } catch {
    return []
  }
}

export function getSavedHashItemsUpdatedAt(): number {
  const n = Number(localStorage.getItem(TS_KEY) || 0)
  return Number.isFinite(n) ? n : 0
}

export function saveHashItems(items: HashItem[]): void {
  localStorage.setItem(ITEMS_KEY, JSON.stringify(items))
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

export function mapHashesResponse(body: {
  items?: HashItem[]
  hashes?: string[]
}): HashItem[] {
  if (body.items?.length) return body.items
  const hashes: string[] = body.hashes || []
  return hashes.map((h, i) => ({
    hash: h,
    label: i === 0 ? 'Bootstrap' : `Сервер #${i - 1}`,
    source: i === 0 ? 'bootstrap' : 'server',
    slot_index: i === 0 ? null : i - 1,
    is_active: true,
    status: 'active',
  }))
}
