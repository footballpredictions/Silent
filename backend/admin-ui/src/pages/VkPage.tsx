import { useEffect, useState, useRef } from 'react'
import { Bot, Cpu, Loader2, Trash2, Plus } from 'lucide-react'

type Status = {
  vk_linked: boolean
  calls_ok: boolean
  auth_error: string | null
  agent_connected: boolean
  agent_enabled: boolean
  vk_user_id: number | null
  hashes_active: number
  max_hashes: number
}

type HashRow = {
  id: string
  slot: number
  hash: string
  is_active: boolean
  fail_count: number
}

type UserRow = { id: string; email: string }

export default function VkPage({ token }: { token: string }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [users, setUsers] = useState<UserRow[]>([])
  const [hashes, setHashes] = useState<HashRow[]>([])
  const [hashUserId, setHashUserId] = useState('')
  const [authUrl, setAuthUrl] = useState('')
  const [oauthPaste, setOauthPaste] = useState('')
  const [manualHash, setManualHash] = useState('')
  const [manualSlot, setManualSlot] = useState(0)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const oauthStateRef = useRef('')

  const authH = { Authorization: `Bearer ${token}` }
  const maxSlots = status?.max_hashes ?? 4
  const slotIndexes = Array.from({ length: maxSlots }, (_, i) => i)
  const jsonH = { ...authH, 'Content-Type': 'application/json' }

  const parseApi = async (res: Response) => {
    const text = await res.text()
    try {
      return { ok: res.ok, data: JSON.parse(text) as Record<string, unknown> }
    } catch {
      return { ok: false, data: { detail: text.slice(0, 200) || `HTTP ${res.status}` } }
    }
  }

  const loadHashes = async (userId: string) => {
    if (!userId) {
      setHashes([])
      return
    }
    const res = await fetch(`/api/admin/vk/hashes?user_id=${userId}`, { headers: authH })
    const { ok, data } = await parseApi(res)
    if (ok) setHashes(data as unknown as HashRow[])
  }

  const load = async () => {
    try {
      const [sr, ur] = await Promise.all([
        fetch('/api/admin/vk/status', { headers: authH }),
        fetch('/api/admin/users?limit=100', { headers: authH }),
      ])
      const s = await parseApi(sr)
      const u = await parseApi(ur)
      if (s.ok) setStatus(s.data as unknown as Status)
      if (u.ok) {
        const list = ((u.data as unknown as UserRow[]) || []).filter(x => !x.email.includes('bootstrap'))
        setUsers(list)
        if (list.length === 1) {
          setHashUserId(list[0].id)
          await loadHashes(list[0].id)
        } else if (hashUserId) {
          await loadHashes(hashUserId)
        }
      }
    } catch {
      setErr('Ошибка загрузки')
    }
  }

  useEffect(() => {
    load()
    fetch('/api/admin/vk/bot-auth/start', { method: 'POST', headers: authH })
      .then(r => r.json())
      .then(d => {
        setAuthUrl(String(d.auth_url || ''))
        oauthStateRef.current = String(d.state || '')
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (hashUserId) loadHashes(hashUserId)
  }, [hashUserId])

  const saveToken = async () => {
    setLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/bot-auth/paste', {
        method: 'POST',
        headers: jsonH,
        body: JSON.stringify({ state: oauthStateRef.current, paste: oauthPaste.trim() }),
      })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'Токен сохранён'))
      setOauthPaste('')
      load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  const connectAgent = async () => {
    setLoading(true)
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/agent/connect', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || data.message || 'Ошибка'))
      setMsg(String(data.message || 'Агент подключён'))
      load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  const disconnectAgent = async () => {
    setLoading(true)
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/agent/disconnect', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'Агент отключён'))
      load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  const addManual = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!hashUserId) {
      setErr('Выберите пользователя')
      return
    }
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/hashes/manual', {
        method: 'POST',
        headers: jsonH,
        body: JSON.stringify({
          hash: manualHash.trim(),
          slot: manualSlot,
          user_id: hashUserId,
        }),
      })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'Хеш добавлен'))
      setManualHash('')
      await loadHashes(hashUserId)
      load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const removeHash = async (slot: number) => {
    if (!hashUserId) return
    setErr('')
    const q = `?user_id=${encodeURIComponent(hashUserId)}`
    const res = await fetch(`/api/admin/vk/hashes/${slot}${q}`, { method: 'DELETE', headers: authH })
    const { ok, data } = await parseApi(res)
    if (!ok) {
      setErr(String(data.detail))
      return
    }
    setMsg(String(data.message))
    await loadHashes(hashUserId)
    load()
  }

  const cleanupBootstrap = async () => {
    if (!confirm('Удалить bootstrap-пользователя и его устройства из БД?')) return
    try {
      const res = await fetch('/api/admin/maintenance/cleanup-bootstrap', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'Готово'))
      load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h1 className="text-xl font-bold">VK — серверный AI-агент</h1>
        <p className="text-[#666] text-sm mt-1">
          Токен VK нужен только серверу для 4 серверных хешей на пользователя (bootstrap — отдельно, только для входа).
        </p>
      </div>

      {msg && <p className="text-sm text-green-400 px-1">{msg}</p>}
      {err && <p className="text-sm text-red-400 px-1">{err}</p>}

      <section className="bg-[#111] border border-[#222] rounded-2xl overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[#222] bg-[#0d0d0d]">
          <span className="w-7 h-7 rounded-full bg-white text-black text-sm font-bold flex items-center justify-center">1</span>
          <h2 className="font-semibold text-sm">Токен агента</h2>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-xs text-[#666]">
            {status?.vk_linked
              ? `✓ Токен действителен (VK ID ${status.vk_user_id ?? '—'})`
              : status?.auth_error || '✗ Нет токена — войдите через VK OAuth'}
          </p>
          {authUrl && (
            <a href={authUrl} target="_blank" rel="noreferrer" className="text-[#4680C2] text-xs hover:underline break-all block">
              Открыть VK OAuth
            </a>
          )}
          <input
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white font-mono"
            placeholder="https://oauth.vk.com/blank.html?code=...&state=..."
            value={oauthPaste}
            onChange={e => setOauthPaste(e.target.value)}
          />
          <button
            onClick={saveToken}
            disabled={loading || !oauthPaste.trim()}
            className="text-xs bg-[#222] border border-[#333] px-3 py-1.5 rounded-lg hover:border-white disabled:opacity-40"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin inline" /> : 'Сохранить токен'}
          </button>
        </div>
      </section>

      <section className="bg-[#111] border border-[#222] rounded-2xl overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[#222] bg-[#0d0d0d]">
          <span className="w-7 h-7 rounded-full bg-white text-black text-sm font-bold flex items-center justify-center">2</span>
          <h2 className="font-semibold text-sm">AI-агент — авто-хеши</h2>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-xs text-[#666] leading-relaxed">
            Агент каждые ~5 мин проверяет 4 слота у каждого пользователя: создаёт недостающие и заменяет сломанные хеши.
          </p>
          {!status?.vk_linked && (
            <p className="text-xs text-amber-400/90">
              Сначала обновите токен VK (шаг 1) — без него звонки не создаются.
            </p>
          )}
          <p className="text-sm text-[#888]">
            {status?.agent_connected ? '✓ Подключён и работает' : status?.agent_enabled ? 'Включён, но токен/calls не OK' : 'Не подключён'}
            {status ? ` · ${status.hashes_active} активных хешей` : ''}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={connectAgent}
              disabled={loading || !status?.vk_linked}
              className="bg-white text-black px-5 py-2.5 rounded-xl text-sm font-semibold hover:bg-[#e5e5e5] disabled:opacity-40"
            >
              Подключить агента
            </button>
            {status?.agent_enabled && (
              <button
                onClick={disconnectAgent}
                disabled={loading}
                className="border border-[#333] px-4 py-2.5 rounded-xl text-sm text-[#aaa] hover:border-red-500 hover:text-red-400"
              >
                Отключить
              </button>
            )}
            <button
              onClick={cleanupBootstrap}
              className="border border-[#333] px-4 py-2.5 rounded-xl text-sm text-[#aaa] hover:border-red-500 hover:text-red-400 inline-flex items-center gap-1"
            >
              <Trash2 className="w-3.5 h-3.5" /> bootstrap-user
            </button>
          </div>
        </div>
      </section>

      <section className="bg-[#111] border border-[#222] rounded-2xl overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[#222] bg-[#0d0d0d]">
          <span className="w-7 h-7 rounded-full bg-white text-black text-sm font-bold flex items-center justify-center">3</span>
          <h2 className="font-semibold text-sm">Ручное управление хешами</h2>
        </div>
        <div className="p-5 space-y-4">
          {users.length > 1 && (
            <select
              value={hashUserId}
              onChange={e => setHashUserId(e.target.value)}
              className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white"
            >
              <option value="">— пользователь —</option>
              {users.map(u => (
                <option key={u.id} value={u.id}>{u.email}</option>
              ))}
            </select>
          )}
          {users.length === 1 && (
            <p className="text-xs text-[#555]">{users[0].email}</p>
          )}

          {slotIndexes.map(slot => {
            const h = hashes.find(x => x.slot === slot && x.is_active)
            return (
              <div key={slot} className="flex items-start gap-3 bg-[#0a0a0a] rounded-xl p-3 border border-[#1a1a1a]">
                <span className="text-[10px] text-[#555] font-mono mt-1 w-10">#{slot}</span>
                {h ? (
                  <>
                    <p className="flex-1 font-mono text-[11px] text-[#bbb] break-all leading-relaxed">{h.hash}</p>
                    <button
                      type="button"
                      onClick={() => removeHash(slot)}
                      className="text-[#555] hover:text-red-400 p-1"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </>
                ) : (
                  <p className="flex-1 text-xs text-[#444] italic">Пусто</p>
                )}
              </div>
            )
          })}

          <form onSubmit={addManual} className="flex gap-2 pt-2 border-t border-[#222]">
            <select
              value={manualSlot}
              onChange={e => setManualSlot(Number(e.target.value))}
              className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-2 py-2 text-xs text-white"
            >
              {slotIndexes.map(slot => (
                <option key={slot} value={slot}>#{slot}</option>
              ))}
            </select>
            <input
              value={manualHash}
              onChange={e => setManualHash(e.target.value)}
              placeholder="Ссылка vk.com/call/join/… или хеш"
              className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white font-mono"
            />
            <button
              type="submit"
              disabled={!manualHash.trim() || !hashUserId}
              className="bg-[#222] border border-[#333] px-3 py-2 rounded-lg hover:border-white disabled:opacity-40"
            >
              <Plus className="w-4 h-4" />
            </button>
          </form>
        </div>
      </section>
    </div>
  )
}
