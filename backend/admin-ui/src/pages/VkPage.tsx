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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const authH = { Authorization: `Bearer ${token}` }
  const jsonH = { ...authH, 'Content-Type': 'application/json' }

  const load = async () => {
    try {
      const [s, h] = await Promise.all([
        fetch('/api/admin/vk/status', { headers: authH }).then(r => r.json()),
        fetch('/api/admin/vk/hashes', { headers: authH }).then(r => r.json()),
      ])
      setStatus(s)
      setHashes(h)
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
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Ошибка')
      window.open(data.auth_url, '_blank', 'width=520,height=720')
      setMsg('Войдите в VK в открывшемся окне. Можно также написать боту для проверки связи.')
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = setInterval(async () => {
        const st = await fetch(`/api/admin/vk/bot-auth/status?state=${data.state}`, { headers: authH })
        const body = await st.json()
        if (body.completed) {
          if (pollRef.current) clearInterval(pollRef.current)
          setMsg(`VK привязан (ID ${body.vk_user_id})`)
          setAuthLoading(false)
          await load()
        }
      }, 2000)
      setTimeout(() => {
        if (pollRef.current) clearInterval(pollRef.current)
        setAuthLoading(false)
      }, 120000)
    } catch (e: any) {
      setErr(e.message)
      setAuthLoading(false)
    }
  }

  const connectAgent = async () => {
    setAgentLoading(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/vk/agent/connect', { method: 'POST', headers: authH })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Ошибка')
      setMsg(data.message)
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

  const addManual = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/hashes/manual', {
        method: 'POST',
        headers: jsonH,
        body: JSON.stringify({ hash: manualHash.trim(), slot: manualSlot }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Ошибка')
      setMsg(data.message)
      setManualHash('')
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  const removeHash = async (slot: number) => {
    setErr('')
    const res = await fetch(`/api/admin/vk/hashes/${slot}`, { method: 'DELETE', headers: authH })
    const data = await res.json()
    if (!res.ok) { setErr(data.detail); return }
    setMsg(data.message)
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
              : <Circle className="w-4 h-4 text-[#555]" />}
            <span className={status?.vk_linked ? 'text-green-400' : 'text-[#888]'}>
              {status?.vk_linked
                ? `VK аккаунт ID ${status.vk_user_id}`
                : 'Не авторизован'}
            </span>
          </div>
          {status?.auth_error && <p className="text-xs text-red-400">{status.auth_error}</p>}
          <p className="text-[10px] text-[#444] leading-relaxed">
            Используется Android API VK (как в клиенте) — нужен для создания звонков и хешей.
          </p>
          <details className="text-xs text-[#555]">
            <summary className="cursor-pointer hover:text-[#888]">Не открывается окно VK?</summary>
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
                const data = await res.json()
                if (!res.ok) throw new Error(data.detail || 'Ошибка')
                setMsg(data.message)
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
            <button onClick={connectAgent} disabled={agentLoading || !status?.vk_linked || !status?.calls_ok}
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
