/** Статичный список серверов 1–4. Сервер 4 не ждёт ответ API. */
export const AI_SERVER_SLOT = 'server4'
export const AI_SERVER_TITLE = 'Сервер 4 для ИИ'

export type VpnServerRow = {
  key: string
  title: string
  public_ip: string
  wdtt_port: number
  online_count: number
  api_base?: string
}

const STATIC_KEYS = ['server1', 'server2', 'server3', AI_SERVER_SLOT] as const

export function slotTitle(slot: string): string {
  const n = String(slot || '').replace(/^server/i, '')
  return n && /^\d+$/.test(n) ? `Сервер ${n}` : slot
}

export function staticVpnServers(): VpnServerRow[] {
  return STATIC_KEYS.map((key) => ({
    key,
    title: key === AI_SERVER_SLOT ? AI_SERVER_TITLE : slotTitle(key),
    public_ip: '',
    wdtt_port: 0,
    online_count: 0,
  }))
}

export function displayVpnServers(fromApi?: VpnServerRow[] | null): VpnServerRow[] {
  const api = Array.isArray(fromApi) ? fromApi : []
  if (api.length === 0) return staticVpnServers()
  const byKey = new Map<string, VpnServerRow>()
  for (const row of api) {
    const k = String(row?.key || '').trim().toLowerCase()
    if (k) byKey.set(k, row)
  }
  const merged = staticVpnServers().map((stub) => {
    const known = byKey.get(stub.key)
    if (!known) return stub
    let title = (known.title || '').trim() || stub.title
    if (stub.key === AI_SERVER_SLOT && (!title || title === slotTitle(AI_SERVER_SLOT))) {
      title = AI_SERVER_TITLE
    }
    return { ...stub, ...known, key: stub.key, title }
  })
  const staticSet = new Set<string>(STATIC_KEYS)
  for (const row of api) {
    const k = String(row?.key || '').trim().toLowerCase()
    if (k && !staticSet.has(k)) merged.push(row)
  }
  return merged
}
