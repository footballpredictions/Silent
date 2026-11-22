import { useEffect, useState, useRef } from 'react'
import { Loader2, Trash2, Plus } from 'lucide-react'
import SearchInput from '../components/SearchInput'
import VkAgentsPanel from '../components/VkAgentsPanel'

type Status = {
  vk_linked: boolean
  calls_ok: boolean
  auth_error: string | null
  agent_connected: boolean
  agent_enabled: boolean
  vk_user_id: number | null
  hashes_active: number
  hashes_per_user?: number
  hashes_dead?: number
  hashes_probe_pending?: number
  probe_budget?: number
  probe_last_run?: string | null
  probe_last_message?: string | null
  users_for_agent?: number
  users_needing_hashes?: number
  max_hashes: number
  agent_last_run?: string | null
  agent_last_status?: string | null
  agent_last_message?: string | null
  agent_flood_cooldown?: boolean
  agent_flood_until?: string | null
  agent_flood_until_msk?: string | null
}

const STATUS_CACHE_KEY = 'silent_vk_status_cache'


function readCachedStatus(): Status | null {
  try {
    const raw = sessionStorage.getItem(STATUS_CACHE_KEY)
    return raw ? (JSON.parse(raw) as Status) : null
  } catch {
    return null
  }
}

type HashRow = {
  id: string
  slot: number
  hash: string
  is_active: boolean
  fail_count: number
}

type UserRow = { id: string; email: string; display_id?: string }

function matchesUser(user: UserRow, query: string) {
  return user.email.toLowerCase().includes(query) || user.display_id?.toLowerCase().includes(query)
}

export default function VkPage({ token }: { token: string }) {
  const [status, setStatus] = useState<Status | null>(() => readCachedStatus())
  const [statusLoading, setStatusLoading] = useState(true)
  const [users, setUsers] = useState<UserRow[]>([])
  const [hashes, setHashes] = useState<HashRow[]>([])
  const [hashUserId, setHashUserId] = useState('')
  const [userQuery, setUserQuery] = useState('')
  const selectedHashUser = useRef('')
  const hashRequest = useRef(0)
  const [authUrl, setAuthUrl] = useState('')
  const [showPasteHint, setShowPasteHint] = useState(false)
  const [oauthPaste, setOauthPaste] = useState('')
  const [manualHash, setManualHash] = useState('')
  const [manualSlot, setManualSlot] = useState(0)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [connectLoading, setConnectLoading] = useState(false)
  const [syncLoading, setSyncLoading] = useState(false)
  const [showReauth, setShowReauth] = useState(false)
  const oauthStateRef = useRef('')
  const pollRef = useRef<number | null>(null)

  const authH = { Authorization: `Bearer ${token}` }
  const maxSlots = status?.max_hashes ?? 4
  const slotIndexes = Array.from({ length: maxSlots }, (_, i) => i)
  const matchingUsers = users.filter(user => matchesUser(user, userQuery.trim().toLowerCase()))
  const jsonH = { ...authH, 'Content-Type': 'application/json' }

  const parseApi = async (res: Response) => {
    const text = await res.text()
    if (res.status === 504 || text.includes('504 Gateway')) {
      return {
        ok: false,
        data: {
          detail:
            'Сервер не успел ответить (504). Обновите страницу — агент мог уже включиться.',
        },
      }
    }
    try {
      return { ok: res.ok, data: JSON.parse(text) as Record<string, unknown> }
    } catch {
      return { ok: false, data: { detail: text.slice(0, 200) || `HTTP ${res.status}` } }
    }
  }

  const selectHashUser = (userId: string) => {
    if (selectedHashUser.current === userId) return
    selectedHashUser.current = userId
    hashRequest.current += 1
    setHashes([])
    setHashUserId(userId)
  }

  const searchHashUsers = (query: string) => {
    setUserQuery(query)
    const selected = users.find(user => user.id === selectedHashUser.current)
    if (selected && !matchesUser(selected, query.trim().toLowerCase())) selectHashUser('')
  }

  const loadHashes = async (userId: string) => {
    if (!userId || selectedHashUser.current !== userId) return
    const request = ++hashRequest.current
    try {
      const res = await fetch(`/api/admin/vk/hashes?user_id=${encodeURIComponent(userId)}`, { headers: authH })
      const { ok, data } = await parseApi(res)
      if (request !== hashRequest.current) return
      if (ok && Array.isArray(data)) setHashes(data)
      else setErr(String(data.detail || 'Не удалось загрузить хеши пользователя'))
    } catch {
      if (request === hashRequest.current) setErr('Не удалось загрузить хеши пользователя')
    }
  }

  const load = async () => {
    try {
      const [sr, ur] = await Promise.all([
        fetch('/api/admin/vk/status', { headers: authH }),
        fetch('/api/admin/users', { headers: authH }),
      ])
      const s = await parseApi(sr)
      const u = await parseApi(ur)
      if (s.ok) {
        const st = s.data as unknown as Status
        setStatus(st)
        try {
          sessionStorage.setItem(STATUS_CACHE_KEY, JSON.stringify(st))
        } catch {
          /* ignore */
        }
      }
      if (u.ok) {
        const list = ((u.data as unknown as UserRow[]) || []).filter(x => !x.email.includes('bootstrap'))
        setUsers(list)
        const selected = selectedHashUser.current
        if (list.length === 1 && !selected) {
          selectHashUser(list[0].id)
        } else if (list.some(user => user.id === selected)) {
          await loadHashes(selected)
        } else {
          selectHashUser('')
        }
      }
    } catch {
      setErr('Ошибка загрузки')
    } finally {
      setStatusLoading(false)
    }
  }

  const stopPoll = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const startStatusPoll = () => {
    stopPoll()
    let ticks = 0
    pollRef.current = window.setInterval(async () => {
      ticks += 1
      await load()
      if (ticks >= 40) stopPoll()
    }, 3000)
  }

  useEffect(() => () => stopPoll(), [])

  const isResultUrl = (text: string) =>
    /blank\.html/i.test(text) &&
    (text.includes('payload=') || text.includes('code=') || text.includes('silent_token='))

  const submitPaste = async (text: string) => {
    const t = text.trim()
    if (!t) return
    setLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/bot-auth/paste', {
        method: 'POST',
        headers: jsonH,
        body: JSON.stringify({ state: oauthStateRef.current, paste: t }),
      })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'Токен сохранён'))
      setOauthPaste('')
      setShowPasteHint(false)
      load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setLoading(false)
    }
  }

  const openAuthPopup = (url: string) => {
    if (!url) return
    setShowPasteHint(true)
    setErr('')
    window.open(url, 'vk_agent_auth', 'width=520,height=720')
  }

  useEffect(() => {
    load()
    fetch('/api/admin/vk/bot-auth/start', { method: 'POST', headers: authH })
      .then(async r => {
        const { ok, data } = await parseApi(r)
        if (ok) {
          setAuthUrl(String(data.auth_url || data.auth_url_calls || ''))
          oauthStateRef.current = String(data.state || '')
        }
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (hashUserId) loadHashes(hashUserId)
  }, [hashUserId])

  const saveToken = async () => {
    await submitPaste(oauthPaste)
  }

  const onPasteField = (text: string) => {
    setOauthPaste(text)
    if (isResultUrl(text)) {
      void submitPaste(text)
    }
  }

  const clearFlood = async () => {
    setSyncLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/agent/clear-flood', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'Пауза снята'))
      startStatusPoll()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setSyncLoading(false)
    }
  }

  const restoreHashes = async () => {
    setSyncLoading(true)
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/agent/restore-hashes', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'Хеши восстановлены'))
      load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setSyncLoading(false)
    }
  }

  const syncHashes = async () => {
    setSyncLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/agent/sync-hashes', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'Запущена синхронизация хешей'))
      startStatusPoll()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setSyncLoading(false)
    }
  }

  const connectAgent = async () => {
    setConnectLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/agent/connect', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || data.message || 'Ошибка'))
      setMsg(String(data.message || 'Агент подключён'))
      await load()
      startStatusPoll()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setConnectLoading(false)
    }
  }

  const disconnectAgent = async () => {
    stopPoll()
    setConnectLoading(true)
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
      setConnectLoading(false)
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

  const tokenStatusLine = () => {
    if (statusLoading && !status) return 'Загрузка статуса…'
    if (status?.vk_linked && !status?.calls_ok) {
      return `⚠ Токен VK ${status.vk_user_id ?? '—'} — звонки недоступны`
    }
    if (status?.vk_linked && status?.calls_ok) {
      return `✓ Токен OK (VK ${status.vk_user_id ?? '—'}), calls.start работает`
    }
    if (statusLoading && status?.calls_ok) {
      return `✓ Токен OK (VK ${status.vk_user_id ?? '—'}), calls.start работает`
    }
    return status?.auth_error || '✗ Нет рабочего токена'
  }


  return (
    <div className="space-y-6 max-w-4xl">
      {msg && <p className="text-sm text-green-400 px-1">{msg}</p>}
      {err && <p className="text-sm text-red-400 px-1">{err}</p>}

      <VkAgentsPanel token={token} />

      <section className="bg-[#111] border border-[#222] rounded-2xl overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[#222] bg-[#0d0d0d]">
          <span className="w-7 h-7 rounded-full bg-white text-black text-sm font-bold flex items-center justify-center">1</span>
          <h2 className="font-semibold text-sm">Токен агента (VK Звонки)</h2>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-xs text-[#666]">{tokenStatusLine()}</p>
          {!statusLoading && !status?.calls_ok && (
            <>
              <p className="text-xs text-[#888] leading-relaxed">
                1. Нажмите «Войти через VK Звонки» → авторизуйтесь → «Продолжить».
                <br />
                2. В popup: <kbd className="text-[#ccc]">Ctrl+L</kbd> → <kbd className="text-[#ccc]">Ctrl+C</kbd> — скопируйте URL.
                <br />
                3. Вставьте ссылку с <code className="text-[#aaa]">blank.html?payload=…</code> ниже.
              </p>
              <button
                type="button"
                onClick={() => openAuthPopup(authUrl)}
                disabled={!authUrl || loading}
                className="w-full text-xs bg-[#4680C2] text-white px-3 py-2.5 rounded-lg font-semibold hover:bg-[#3a6fad] disabled:opacity-40"
              >
                Войти через VK Звонки
              </button>
            </>
          )}
          {status?.calls_ok && (
            <details
              className="text-xs"
              open={showReauth}
              onToggle={e => setShowReauth((e.target as HTMLDetailsElement).open)}
            >
              <summary className="cursor-pointer text-[#777] hover:text-[#aaa]">
                Обновить токен VK (если сломается)
              </summary>
              <div className="mt-3 space-y-2">
                <p className="text-[11px] text-[#666] leading-relaxed">
                  Тот же вход через VK Звonки → «Продолжить» → Ctrl+L → Ctrl+C → вставить URL с payload=…
                </p>
                <button
                  type="button"
                  onClick={() => openAuthPopup(authUrl)}
                  disabled={!authUrl || loading}
                  className="w-full text-xs bg-[#4680C2] text-white px-3 py-2 rounded-lg font-semibold hover:bg-[#3a6fad] disabled:opacity-40"
                >
                  Войти заново
                </button>
              </div>
            </details>
          )}
          {(showPasteHint || oauthPaste || (!statusLoading && !status?.calls_ok)) && (
            <div className="space-y-2 rounded-lg border border-[#333] bg-[#0d0d0d] p-3">
              <textarea
                className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-[11px] text-white font-mono min-h-[64px]"
                placeholder="https://oauth.vk.com/blank.html?payload=…"
                value={oauthPaste}
                onChange={e => onPasteField(e.target.value)}
                onPaste={e => {
                  const t = e.clipboardData.getData('text')
                  if (t) setTimeout(() => onPasteField(t), 0)
                }}
              />
              <button
                onClick={saveToken}
                disabled={loading || !oauthPaste.trim()}
                className="w-full text-xs bg-white text-black px-3 py-2 rounded-lg font-semibold hover:bg-[#e5e5e5] disabled:opacity-40"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin inline" /> : 'Сохранить токен'}
              </button>
            </div>
          )}
        </div>
      </section>

      <details className="rounded-xl border border-[#2a2a2a] bg-[#111] p-4">
        <summary className="cursor-pointer text-sm text-[#ccc]">Дополнительные операции с хешами</summary>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={connectAgent} disabled={connectLoading || !status?.calls_ok} className="border border-[#333] rounded-lg px-3 py-2 text-sm disabled:opacity-40">Включить обоих агентов</button>
          <button type="button" onClick={disconnectAgent} disabled={connectLoading} className="border border-[#333] rounded-lg px-3 py-2 text-sm disabled:opacity-40">Остановить обоих агентов</button>
          <button type="button" onClick={restoreHashes} disabled={syncLoading} className="border border-[#333] rounded-lg px-3 py-2 text-sm disabled:opacity-40">Восстановить скрытые хеши</button>
          <button type="button" onClick={syncHashes} disabled={syncLoading || !status?.calls_ok} className="border border-[#333] rounded-lg px-3 py-2 text-sm disabled:opacity-40">Создать недостающие хеши</button>
          {status?.agent_flood_cooldown && <button type="button" onClick={clearFlood} disabled={syncLoading} className="border border-[#333] rounded-lg px-3 py-2 text-sm disabled:opacity-40">Снять паузу основного агента</button>}
          <button type="button" onClick={cleanupBootstrap} className="border border-[#333] rounded-lg px-3 py-2 text-sm">Очистить bootstrap-пользователя</button>
        </div>
      </details>

      <section className="bg-[#111] border border-[#222] rounded-2xl overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[#222] bg-[#0d0d0d]">
          <span className="w-7 h-7 rounded-full bg-white text-black text-sm font-bold flex items-center justify-center">3</span>
          <h2 className="font-semibold text-sm">Ручное управление хешами</h2>
        </div>
        <div className="p-5 space-y-4">
          {users.length > 1 && (
            <div className="space-y-2">
              <SearchInput value={userQuery} onChange={searchHashUsers} placeholder="Поиск по email или ID" />
              <select
                aria-label="Пользователь"
                value={hashUserId}
                onChange={e => selectHashUser(e.target.value)}
                disabled={matchingUsers.length === 0}
                className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white disabled:opacity-50"
              >
                <option value="">— пользователь —</option>
                {matchingUsers.map(u => (
                  <option key={u.id} value={u.id}>{u.email}</option>
                ))}
              </select>
              {matchingUsers.length === 0 && <p role="status" className="text-xs text-[#888]">Пользователи не найдены</p>}
            </div>
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
              className="min-w-0 flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white font-mono"
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
