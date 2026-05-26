import { useState, useEffect } from 'react'
import { Key, RefreshCw, CheckCircle, XCircle, AlertTriangle, Plus, Zap, ExternalLink } from 'lucide-react'

type VkStatus = {
  configured: boolean
  has_password: boolean
  has_token: boolean
  auth_ok: boolean
  auth_error: string | null
  vk_user_id: number | null
  token_capture_url: string
}

export default function VkPage({ token }: { token: string }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [accessToken, setAccessToken] = useState('')
  const [hashes, setHashes] = useState<any[]>([])
  const [status, setStatus] = useState<VkStatus | null>(null)
  const [manualHash, setManualHash] = useState('')
  const [manualSlot, setManualSlot] = useState(0)
  const [saving, setSaving] = useState(false)
  const [recreating, setRecreating] = useState(false)
  const [creatingSlot, setCreatingSlot] = useState<number | null>(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const fetchAll = async () => {
    try {
      const [hRes, sRes] = await Promise.all([
        fetch('/api/admin/vk/hashes', { headers: { Authorization: `Bearer ${token}` } }),
        fetch('/api/admin/vk/status', { headers: { Authorization: `Bearer ${token}` } }),
      ])
      setHashes(await hRes.json())
      setStatus(await sRes.json())
    } catch {
      setErr('Не удалось загрузить данные VK')
    }
  }

  useEffect(() => { fetchAll() }, [])

  const saveCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMsg('')
    setErr('')
    try {
      const body: Record<string, string> = {}
      if (accessToken.trim()) body.access_token = accessToken.trim()
      else {
        body.login = login
        body.password = password
      }
      const res = await fetch('/api/admin/vk/credentials', { method: 'POST', headers, body: JSON.stringify(body) })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Ошибка')
      setMsg(data.message || 'Сохранено')
      setLogin('')
      setPassword('')
      setAccessToken('')
      await fetchAll()
    } catch (e: any) {
      setErr(e.message || 'Ошибка сохранения')
    }
    setSaving(false)
  }

  const testAuth = async () => {
    setMsg('')
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/auth/test', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Auth failed')
      setMsg(`Авторизация OK — VK user_id ${data.vk_user_id}`)
      await fetchAll()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  const recreateHashes = async () => {
    setRecreating(true)
    setMsg('')
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/recreate', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      if (!data.success && !data.message?.includes('частично')) {
        setErr(data.message || 'Ошибка пересоздания')
      } else {
        setMsg(data.message)
      }
      setTimeout(fetchAll, 1500)
    } catch {
      setErr('Ошибка сети')
    }
    setRecreating(false)
  }

  const createSlot = async (slot: number) => {
    setCreatingSlot(slot)
    setMsg('')
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/hashes/create', {
        method: 'POST',
        headers,
        body: JSON.stringify({ slot }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.message || 'Ошибка')
      setMsg(data.message || `Слот ${slot} создан`)
      await fetchAll()
    } catch (e: any) {
      setErr(e.message)
    }
    setCreatingSlot(null)
  }

  const addManual = async (e: React.FormEvent) => {
    e.preventDefault()
    setMsg('')
    setErr('')
    try {
      const res = await fetch('/api/admin/vk/hashes/manual', {
        method: 'POST',
        headers,
        body: JSON.stringify({ hash: manualHash.trim(), slot: manualSlot }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Ошибка')
      setMsg(data.message)
      setManualHash('')
      await fetchAll()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold">VK Аккаунт и тоннели</h1>

      {/* Auth status */}
      <div className={`border rounded-xl p-4 ${status?.auth_ok ? 'border-green-900/50 bg-green-950/20' : 'border-yellow-900/50 bg-yellow-950/10'}`}>
        <div className="flex items-center gap-2 mb-2">
          {status?.auth_ok
            ? <CheckCircle className="w-4 h-4 text-green-400" />
            : <AlertTriangle className="w-4 h-4 text-yellow-500" />}
          <span className="text-sm font-medium">
            {status?.auth_ok
              ? `VK авторизован (ID ${status.vk_user_id})`
              : 'VK не авторизован — хеши не создаются'}
          </span>
        </div>
        {status?.auth_error && (
          <p className="text-xs text-red-400 mb-2">{status.auth_error}</p>
        )}
        <button onClick={testAuth}
          className="text-xs bg-[#1a1a1a] border border-[#333] px-3 py-1.5 rounded-lg hover:border-white">
          Проверить авторизацию
        </button>
      </div>

      {/* Token (recommended) */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6">
        <h2 className="font-semibold mb-1 flex items-center gap-2"><Key className="w-4 h-4" /> VK Access Token</h2>
        <p className="text-[#555] text-xs mb-3">
          Рекомендуется: токен Android-клиента (client_id 6287487) — тот же способ, что у proxy-turn-vk.
          AI-агент сохранит токен и будет им создавать/заменять хеши автоматически.
        </p>
        {status?.token_capture_url && (
          <a href={status.token_capture_url} target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-blue-400 hover:underline mb-3">
            <ExternalLink className="w-3 h-3" /> Получить токен в браузере
          </a>
        )}
        <form onSubmit={saveCredentials} className="space-y-3">
          <textarea
            value={accessToken}
            onChange={e => setAccessToken(e.target.value)}
            placeholder="vk1.a.... или вставьте из oauth.vk.com/blank.html#access_token=..."
            rows={3}
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 text-xs text-white font-mono focus:outline-none focus:border-[#444]"
          />
          <p className="text-[#444] text-xs">— или логин/пароль (может не работать без 2FA):</p>
          <input
            type="text" value={login} onChange={e => setLogin(e.target.value)}
            placeholder="Логин (телефон или email)"
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-[#444]"
          />
          <input
            type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="Пароль"
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-[#444]"
          />
          <button type="submit" disabled={saving}
            className="bg-white text-black px-5 py-2.5 rounded-lg text-sm font-semibold hover:bg-[#e0e0e0] disabled:opacity-50 transition-colors">
            {saving ? 'Сохраняем...' : 'Сохранить авторизацию'}
          </button>
        </form>
      </div>

      {/* Hashes */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h2 className="font-semibold">VK Хеши (TURN туннели)</h2>
          <button onClick={recreateHashes} disabled={recreating}
            className="flex items-center gap-2 bg-[#1a1a1a] border border-[#2a2a2a] px-4 py-2 rounded-lg text-xs hover:border-white transition-colors disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${recreating ? 'animate-spin' : ''}`} />
            Создать все 3
          </button>
        </div>

        <div className="flex gap-2 mb-4">
          {[0, 1, 2].map(slot => (
            <button key={slot} onClick={() => createSlot(slot)} disabled={creatingSlot !== null}
              className="flex items-center gap-1 bg-[#1a1a1a] border border-[#2a2a2a] px-3 py-1.5 rounded-lg text-xs hover:border-green-600 disabled:opacity-50">
              <Zap className={`w-3 h-3 ${creatingSlot === slot ? 'animate-pulse' : ''}`} />
              Слот {slot}
            </button>
          ))}
        </div>

        {hashes.length === 0 ? (
          <div className="text-center py-6 text-[#555]">
            <AlertTriangle className="w-8 h-8 mx-auto mb-2 text-yellow-500" />
            <p className="text-sm">Хеши не созданы. Сохраните VK токен и нажмите «Слот 0» или «Создать все 3».</p>
          </div>
        ) : (
          <div className="space-y-2 mb-4">
            {hashes.map(h => (
              <div key={h.id} className="flex items-center gap-3 bg-[#151515] rounded-lg px-4 py-3">
                {h.is_active
                  ? <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
                  : <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />}
                <span className="text-xs text-[#555] w-12">Слот {h.slot}</span>
                <span className="font-mono text-xs flex-1 text-[#ccc] break-all">{h.hash}</span>
                <span className="text-xs text-[#555]">Сбоев: {h.fail_count}</span>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={addManual} className="border-t border-[#222] pt-4 space-y-2">
          <p className="text-xs text-[#555] flex items-center gap-1"><Plus className="w-3 h-3" /> Добавить хеш вручную</p>
          <div className="flex gap-2">
            <select value={manualSlot} onChange={e => setManualSlot(Number(e.target.value))}
              className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white">
              <option value={0}>Слот 0</option>
              <option value={1}>Слот 1</option>
              <option value={2}>Слот 2</option>
            </select>
            <input
              value={manualHash}
              onChange={e => setManualHash(e.target.value)}
              placeholder="Хеш или ссылка vk.com/call/join/…"
              className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-xs text-white font-mono"
            />
            <button type="submit" className="bg-[#222] border border-[#333] px-4 py-2 rounded-lg text-xs hover:border-white">
              Добавить
            </button>
          </div>
        </form>
      </div>

      {msg && (
        <div className="bg-[#111] border border-green-900/40 rounded-xl px-4 py-3 text-sm text-green-400">{msg}</div>
      )}
      {err && (
        <div className="bg-[#111] border border-red-900/40 rounded-xl px-4 py-3 text-sm text-red-400">{err}</div>
      )}

      <div className="bg-[#111] border border-yellow-900/50 rounded-xl p-4">
        <p className="text-xs text-yellow-500/80 leading-relaxed">
          <strong>AI-агент</strong> каждые 5 мин проверяет хеши и автоматически заменяет мёртвые через тот же VK токен.
          При завершении звонка в VK нажимайте «Просто завершить», не «Завершить для всех».
        </p>
      </div>
    </div>
  )
}
