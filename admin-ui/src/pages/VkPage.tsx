import { useEffect, useState, useRef } from 'react'
import { Loader2, Trash2, Plus } from 'lucide-react'

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

function formatMskFromUtc(raw: string | null | undefined): string | null {
  if (!raw) return null
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/)
  if (!m) return raw
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]))
  return d.toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' МСК'
}

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

type UserRow = { id: string; email: string }

export default function VkPage({ token }: { token: string }) {
  const [status, setStatus] = useState<Status | null>(() => readCachedStatus())
  const [statusLoading, setStatusLoading] = useState(true)
  const [users, setUsers] = useState<UserRow[]>([])
  const [hashes, setHashes] = useState<HashRow[]>([])
  const [hashUserId, setHashUserId] = useState('')
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
        if (list.length === 1) {
          setHashUserId(list[0].id)
          await loadHashes(list[0].id)
        } else if (hashUserId) {
          await loadHashes(hashUserId)
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

  const agentStatusLine = () => {
    if (statusLoading && !status) return 'Загрузка…'
    const floodMsk = status?.agent_flood_until_msk || formatMskFromUtc(status?.agent_flood_until)
    if (status?.agent_flood_cooldown) {
      return `⏸ Пауза создания хешей (VK flood на calls.start) до ${floodMsk ?? '—'}`
    }
    if (status?.agent_connected) {
      const need = status.users_needing_hashes ?? 0
      const dead = status.hashes_dead ?? 0
      const pending = status.hashes_probe_pending ?? 0
      const budget = status.probe_budget ?? 8
      let base = `✓ Агент работает · ${status.hashes_per_user ?? status.hashes_active} хешей · liveness ${budget}/цикл`
      if (dead > 0) base += ` · ${dead} слотов с ошибкой 1`
      if (pending > 0) base += ` · ${pending} ждут повторной пробы`
      return need > 0 ? `${base} · ${need} пользов. без полного набора (4/4)` : base
    }
    if (status?.agent_enabled && status?.calls_ok) {
      return `⏳ Агент включён, создаются хеши… (${status.hashes_active} уже есть). Подождите 1–3 мин и обновите страницу.`
    }
    if (status?.agent_enabled) {
      return '⚠ Агент включён, но токен VK/calls не OK'
    }
    if (status?.calls_ok) {
      return 'Токен готов — нажмите «Подключить агента»'
    }
    return 'Сначала войдите через VK Звонки (шаг 1)'
  }

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h1 className="text-lg font-bold">VK — серверный AI-агент</h1>
        <p className="text-[#666] text-sm mt-1">
          Сервер создаёт до 4 хешей VK-звонков на каждого пользователя и следит, чтобы они не умирали.
        </p>
      </div>

      {msg && <p className="text-sm text-green-400 px-1">{msg}</p>}
      {err && <p className="text-sm text-red-400 px-1">{err}</p>}

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

      <section className="bg-[#111] border border-[#222] rounded-2xl overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-[#222] bg-[#0d0d0d]">
          <span className="w-7 h-7 rounded-full bg-white text-black text-sm font-bold flex items-center justify-center">2</span>
          <h2 className="font-semibold text-sm">AI-агент — авто-хеши</h2>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-xs text-[#666] leading-relaxed">
            Агент каждые ~15 мин проверяет живые join-хеши (анонимный preview, без TURN) и заполняет
            пустые и мёртвые слоты (ошибка 1). Протухший anonym_token на клиенте — не поломка слота.
          </p>
          <p
            className={`text-sm ${
              status?.agent_flood_cooldown
                ? 'text-amber-400'
                : status?.agent_connected
                  ? 'text-green-400'
                  : status?.agent_enabled
                    ? 'text-amber-400/90'
                    : 'text-[#888]'
            }`}
          >
            {agentStatusLine()}
          </p>
          {status?.agent_flood_cooldown && (
            <p className="text-[11px] text-[#666] leading-relaxed">
              Это пауза **нашего** сервера после VK error 9 на создании звонков (`calls.start`), не блокировка аккаунта.
              Проверка живых хешей (preview) эту паузу больше не ставит. «Снять паузу» сразу создаёт недостающие хеши, без пачки проб.
            </p>
          )}
          {status?.agent_last_message && (
            <p className="text-[11px] text-[#555] leading-relaxed border border-[#222] rounded-lg px-3 py-2 bg-[#0a0a0a]">
              <span className="text-[#777]">Последний запуск</span>{' '}
              {status.agent_last_run ? `(${status.agent_last_run}): ` : ': '}
              {status.agent_last_message}
            </p>
          )}
          {status?.probe_last_message && (
            <p className="text-[11px] text-[#555] leading-relaxed border border-[#222] rounded-lg px-3 py-2 bg-[#0a0a0a]">
              <span className="text-[#777]">Liveness</span>{' '}
              {status.probe_last_run ? `(${status.probe_last_run}): ` : ': '}
              {status.probe_last_message}
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {!status?.agent_enabled ? (
              <button
                onClick={connectAgent}
                disabled={connectLoading || !status?.calls_ok}
                className="bg-white text-black px-5 py-2.5 rounded-xl text-sm font-semibold hover:bg-[#e5e5e5] disabled:opacity-40 inline-flex items-center gap-2 min-w-[180px] justify-center"
              >
                {connectLoading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Подключаем…
                  </>
                ) : (
                  'Подключить агента'
                )}
              </button>
            ) : (
              <>
                <button
                  onClick={disconnectAgent}
                  disabled={connectLoading}
                  className="border border-[#333] px-4 py-2.5 rounded-xl text-sm text-[#aaa] hover:border-red-500 hover:text-red-400 inline-flex items-center gap-2"
                >
                  {connectLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  Отключить агента
                </button>
                {status?.agent_flood_cooldown && status?.calls_ok && (
                  <button
                    type="button"
                    onClick={clearFlood}
                    disabled={syncLoading}
                    className="bg-amber-500/20 border border-amber-500/40 px-4 py-2.5 rounded-xl text-sm text-amber-300 hover:bg-amber-500/30 inline-flex items-center gap-2 disabled:opacity-40"
                  >
                    {syncLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                    Снять паузу и создать хеши
                  </button>
                )}
                <button
                  type="button"
                  onClick={restoreHashes}
                  disabled={syncLoading}
                  title="Вернуть хеши, которые агент ошибочно скрыл (is_active=false)"
                  className="border border-[#333] px-4 py-2.5 rounded-xl text-sm text-[#aaa] hover:border-amber-500 hover:text-amber-400 inline-flex items-center gap-2 disabled:opacity-40"
                >
                  Восстановить скрытые
                </button>
                <button
                  type="button"
                  onClick={syncHashes}
                  disabled={syncLoading || !status?.calls_ok || status?.agent_flood_cooldown}
                  className="border border-[#333] px-4 py-2.5 rounded-xl text-sm text-[#aaa] hover:border-white hover:text-white inline-flex items-center gap-2 disabled:opacity-40"
                >
                  {syncLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  Создать хеши сейчас
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => load()}
              className="border border-[#333] px-4 py-2.5 rounded-xl text-sm text-[#aaa] hover:border-[#555]"
            >
              Обновить статус
            </button>
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
