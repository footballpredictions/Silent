import { useState, useEffect, useRef } from 'react'
import { Bot, Cpu, Trash2, Plus, CheckCircle2, Circle, Loader2 } from 'lucide-react'

type Status = {
  bot_url: string
  vk_linked: boolean
  calls_ok: boolean
  vk_user_id: number | null
  auth_error: string | null
  agent_connected: boolean
  agent_enabled: boolean
  env_token_set?: boolean
  env_token_warn?: string | null
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

export default function VkPage({ token }: { token: string }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [hashes, setHashes] = useState<HashRow[]>([])
  const [manualHash, setManualHash] = useState('')
  const [manualSlot, setManualSlot] = useState(0)
  const [authLoading, setAuthLoading] = useState(false)
  const [agentLoading, setAgentLoading] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [oauthPaste, setOauthPaste] = useState('')
  const [authUrl, setAuthUrl] = useState('')
  const oauthStateRef = useRef('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const authH = { Authorization: `Bearer ${token}` }
  const jsonH = { ...authH, 'Content-Type': 'application/json' }

  const parseApi = async (res: Response) => {
    const text = await res.text()
    try {
      return { ok: res.ok, data: JSON.parse(text) as Record<string, unknown> }
    } catch {
      return { ok: false, data: { detail: text.slice(0, 200) || `HTTP ${res.status}` } }
    }
  }

  const load = async () => {
    try {
      const [sr, hr] = await Promise.all([
        fetch('/api/admin/vk/status', { headers: authH }),
        fetch('/api/admin/vk/hashes', { headers: authH }),
      ])
      const s = await parseApi(sr)
      const h = await parseApi(hr)
      if (s.ok) setStatus(s.data as unknown as Status)
      if (h.ok) setHashes(h.data as unknown as HashRow[])
    } catch {
      setErr('Ошибка загрузки')
    }
  }

  useEffect(() => {
    load()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  const startBotAuth = async () => {
    setAuthLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/bot-auth/start', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      oauthStateRef.current = String(data.state || '')
      setAuthUrl(String(data.auth_url || ''))
      window.open(String(data.auth_url), '_blank', 'width=520,height=720')
      setMsg(String(data.paste_hint || 'Войдите в VK, затем вставьте URL из адресной строки blank.html'))
    } catch (e: any) {
      setErr(e.message)
    }
    setAuthLoading(false)
  }

  const submitOAuthPaste = async (e: React.FormEvent) => {
    e.preventDefault()
    setAuthLoading(true)
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/bot-auth/paste', {
        method: 'POST',
        headers: jsonH,
        body: JSON.stringify({ state: oauthStateRef.current, paste: oauthPaste.trim() }),
      })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(`VK привязан (ID ${data.vk_user_id})`)
      setOauthPaste('')
      await load()
    } catch (ex: any) {
      setErr(ex.message)
    }
    setAuthLoading(false)
  }

  const connectAgent = async () => {
    setAgentLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/agent/connect', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'OK'))
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
    setAgentLoading(false)
  }

  const disconnectAgent = async () => {
    setAgentLoading(true)
    await fetch('/api/admin/vk/agent/disconnect', { method: 'POST', headers: authH })
    setMsg('Агент отключён')
    await load()
    setAgentLoading(false)
  }

  const syncEnvToken = async () => {
    setAgentLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/agent/sync-env', { method: 'POST', headers: authH })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'OK'))
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
    setAgentLoading(false)
  }

  const addManual = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/hashes/manual', {
        method: 'POST',
        headers: jsonH,
        body: JSON.stringify({ hash: manualHash.trim(), slot: manualSlot }),
      })
      const { ok, data } = await parseApi(res)
      if (!ok) throw new Error(String(data.detail || 'Ошибка'))
      setMsg(String(data.message || 'OK'))
      setManualHash('')
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  const removeHash = async (slot: number) => {
    setErr('')
    const res = await fetch(`/api/admin/vk/hashes/${slot}`, { method: 'DELETE', headers: authH })
    const { ok, data } = await parseApi(res)
    if (!ok) { setErr(String(data.detail)); return }
    setMsg(String(data.message))
    await load()
  }

  const step = (n: number, title: string, children: React.ReactNode) => (
    <section className="bg-[#111] border border-[#222] rounded-2xl overflow-hidden">
      <div className="flex items-center gap-3 px-5 py-4 border-b border-[#222] bg-[#0d0d0d]">
        <span className="w-7 h-7 rounded-full bg-white text-black text-sm font-bold flex items-center justify-center">{n}</span>
        <h2 className="font-semibold text-sm">{title}</h2>
      </div>
      <div className="p-5">{children}</div>
    </section>
  )

  return (
    <div className="space-y-5 max-w-xl">
      <div>
        <h1 className="text-xl font-bold">VK тоннели</h1>
        <p className="text-[#666] text-xs mt-1">Три шага: бот → агент → хеши вручную при необходимости</p>
      </div>

      {step(1, 'Авторизация через бота Silent', (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm">
            {status?.vk_linked && status?.calls_ok
              ? <CheckCircle2 className="w-4 h-4 text-green-400" />
              : status?.vk_linked
              ? <Circle className="w-4 h-4 text-amber-400" />
              : <Circle className="w-4 h-4 text-[#555]" />}
            <span className={status?.vk_linked && status?.calls_ok ? 'text-green-400' : status?.vk_linked ? 'text-amber-400' : 'text-[#888]'}>
              {status?.vk_linked && status?.calls_ok
                ? `VK аккаунт ID ${status.vk_user_id}`
                : status?.vk_linked
                ? `Токен OK (ID ${status.vk_user_id}), нажмите «Сохранить» или «Подключить агента»`
                : 'Не авторизован'}
            </span>
          </div>
          {status?.auth_error && <p className="text-xs text-red-400">{status.auth_error}</p>}
          {status?.env_token_warn && (
            <p className="text-[10px] text-amber-500/90">{status.env_token_warn}</p>
          )}
          {status?.env_token_set && !status?.env_token_warn && (
            <p className="text-[10px] text-green-500/80">
              На сервере задан VK_AGENT_ACCESS_TOKEN в .env.
            </p>
          )}
          {!status?.env_token_set && status?.auth_error?.includes('Android') && (
            <p className="text-[10px] text-[#666] leading-relaxed">
              Добавьте в .env на сервере: VK_AGENT_ACCESS_TOKEN=vk1.a… (OAuth client_id 6287487).
            </p>
          )}
          <p className="text-[10px] text-[#444] leading-relaxed">
            Используется Android API VK (как в клиенте) — нужен для создания звонков и хешей.
          </p>
          <form onSubmit={submitOAuthPaste} className="space-y-2">
            <p className="text-[10px] text-[#666]">
              1. «Войти через VK» → 2. скопируйте URL <span className="text-[#888]">blank.html?code=...</span> → 3. вставьте сюда
            </p>
            <p className="text-[10px] text-amber-600/90">
              Не вставляйте vk1.a... с ПК — VK привязывает token к IP. Сервер сам обменяет code.
            </p>
            {authUrl && (
              <a href={authUrl} target="_blank" rel="noreferrer"
                className="block text-[10px] text-[#4680C2] hover:underline break-all">
                Открыть VK OAuth (если окно не открылось)
              </a>
            )}
            <input
              value={oauthPaste}
              onChange={e => setOauthPaste(e.target.value)}
              placeholder="https://oauth.vk.com/blank.html?code=...&state=..."
              className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white font-mono"
            />
            <button type="submit" disabled={authLoading || !oauthPaste.trim()}
              className="text-xs bg-[#222] border border-[#333] px-3 py-1.5 rounded-lg hover:border-white disabled:opacity-40">
              Сохранить токен
            </button>
          </form>
          <details className="text-xs text-[#555]">
            <summary className="cursor-pointer hover:text-[#888]">Вход по паролю VK (если OAuth не работает)</summary>
            <form className="mt-3 space-y-2" onSubmit={async e => {
              e.preventDefault()
              const fd = new FormData(e.currentTarget)
              setAuthLoading(true)
              setErr('')
              try {
                const res = await fetch('/api/admin/vk/bot-auth/password', {
                  method: 'POST',
                  headers: jsonH,
                  body: JSON.stringify({ login: fd.get('login'), password: fd.get('password') }),
                })
                const { ok, data } = await parseApi(res)
                if (!ok) throw new Error(String(data.detail || 'Ошибка'))
                setMsg(String(data.message))
                await load()
              } catch (ex: any) { setErr(ex.message) }
              setAuthLoading(false)
            }}>
              <input name="login" placeholder="Телефон или email VK" required
                className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white" />
              <input name="password" type="password" placeholder="Пароль VK" required
                className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white" />
              <button type="submit" className="text-xs border border-[#333] px-3 py-1.5 rounded-lg hover:border-white">
                Войти по паролю
              </button>
            </form>
          </details>
          <div className="flex flex-wrap gap-2">
            <button onClick={startBotAuth} disabled={authLoading}
              className="inline-flex items-center gap-2 bg-[#4680C2] hover:bg-[#5a94d6] text-white px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50">
              {authLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bot className="w-4 h-4" />}
              Войти через VK
            </button>
            {status?.env_token_set && (
              <button onClick={syncEnvToken} disabled={agentLoading}
                className="inline-flex items-center gap-2 border border-[#333] px-4 py-2.5 rounded-xl text-sm text-[#aaa] hover:border-[#555] disabled:opacity-50">
                Проверить .env токен
              </button>
            )}
            {status?.bot_url && (
              <a href={status.bot_url} target="_blank" rel="noreferrer"
                className="inline-flex items-center gap-2 border border-[#333] px-4 py-2.5 rounded-xl text-sm text-[#aaa] hover:border-[#555]">
                Открыть бота
              </a>
            )}
          </div>
        </div>
      ))}

      {step(2, 'AI-агент — авто-хеши', (
        <div className="space-y-4">
          <p className="text-xs text-[#666] leading-relaxed">
            Агент каждые 5 мин проверяет 3 слота. Сломанный хеш заменяется автоматически и рассылается клиентам.
          </p>
          <div className="flex items-center gap-2 text-sm">
            <Cpu className={`w-4 h-4 ${status?.agent_connected ? 'text-green-400' : 'text-[#555]'}`} />
            <span className={status?.agent_connected ? 'text-green-400' : 'text-[#888]'}>
              {status?.agent_connected
                ? `Работает · ${status.hashes_active}/${status.max_hashes} хешей`
                : 'Не подключён'}
            </span>
          </div>
          {status?.agent_connected ? (
            <button onClick={disconnectAgent} disabled={agentLoading}
              className="border border-[#444] text-[#ccc] px-4 py-2.5 rounded-xl text-sm hover:border-red-500 hover:text-red-400 disabled:opacity-50">
              Отключить агента
            </button>
          ) : (
            <button onClick={connectAgent} disabled={agentLoading || !status?.vk_linked}
              className="bg-white text-black px-5 py-2.5 rounded-xl text-sm font-semibold hover:bg-[#e5e5e5] disabled:opacity-40 disabled:cursor-not-allowed">
              {agentLoading ? 'Подключение…' : 'Подключить агента'}
            </button>
          )}
        </div>
      ))}

      {step(3, 'Ручное управление хешами', (
        <div className="space-y-4">
          {[0, 1, 2].map(slot => {
            const h = hashes.find(x => x.slot === slot && x.is_active)
            return (
              <div key={slot} className="flex items-start gap-3 bg-[#0a0a0a] rounded-xl p-3 border border-[#1a1a1a]">
                <span className="text-[10px] text-[#555] font-mono mt-1 w-10">#{slot}</span>
                {h ? (
                  <>
                    <p className="flex-1 font-mono text-[11px] text-[#bbb] break-all leading-relaxed">{h.hash}</p>
                    <button onClick={() => removeHash(slot)} className="text-[#555] hover:text-red-400 p-1">
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
            <select value={manualSlot} onChange={e => setManualSlot(Number(e.target.value))}
              className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-2 py-2 text-xs text-white">
              <option value={0}>#0</option>
              <option value={1}>#1</option>
              <option value={2}>#2</option>
            </select>
            <input value={manualHash} onChange={e => setManualHash(e.target.value)}
              placeholder="Ссылка vk.com/call/join/… или хеш"
              className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white font-mono" />
            <button type="submit" className="bg-[#222] border border-[#333] px-3 py-2 rounded-lg hover:border-white">
              <Plus className="w-4 h-4" />
            </button>
          </form>
        </div>
      ))}

      {msg && <p className="text-sm text-green-400 px-1">{msg}</p>}
      {err && <p className="text-sm text-red-400 px-1">{err}</p>}
    </div>
  )
}
