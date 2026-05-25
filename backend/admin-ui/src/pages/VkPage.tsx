import { useState, useEffect } from 'react'
import { Key, RefreshCw, CheckCircle, XCircle, AlertTriangle, Eye, EyeOff, Check, ShieldCheck, ShieldX } from 'lucide-react'

type Status = 'idle' | 'loading' | 'success' | 'error'

function StatusBadge({ status, msg }: { status: Status; msg: string }) {
  if (status === 'idle' || !msg) return null
  const styles: Record<string, string> = {
    loading: 'bg-[#1a1a1a] border-[#333] text-[#aaa]',
    success: 'bg-green-500/10 border-green-500/30 text-green-400',
    error:   'bg-red-500/10  border-red-500/30  text-red-400',
  }
  return (
    <div className={`border rounded-lg px-3 py-2 text-xs leading-relaxed ${styles[status]}`}>
      {msg}
    </div>
  )
}

export default function VkPage({ token }: { token: string }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [hashes, setHashes] = useState<any[]>([])

  const [saveStatus, setSaveStatus]     = useState<Status>('idle')
  const [saveMsg, setSaveMsg]           = useState('')
  const [authStatus, setAuthStatus]     = useState<Status>('idle')
  const [authMsg, setAuthMsg]           = useState('')
  const [recreateStatus, setRecreateStatus] = useState<Status>('idle')
  const [recreateMsg, setRecreateMsg]   = useState('')

  const api = (path: string, opts?: RequestInit) =>
    fetch(path, { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...opts?.headers }, ...opts })

  const fetchHashes = async () => {
    try {
      const res = await api('/api/admin/vk/hashes')
      if (res.ok) setHashes(await res.json())
    } catch {}
  }

  const fetchCredentials = async () => {
    try {
      const res = await api('/api/admin/vk/credentials')
      if (res.ok) {
        const data = await res.json()
        if (data.login) setLogin(data.login)
      }
    } catch {}
  }

  useEffect(() => {
    fetchHashes()
    fetchCredentials()
  }, [])

  // ── Save credentials ──────────────────────────────────────────────
  const saveCredentials = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!login.trim() || !password.trim()) return
    setSaveStatus('loading'); setSaveMsg('Сохраняем...')
    try {
      const res = await api('/api/admin/vk/credentials', {
        method: 'POST', body: JSON.stringify({ login, password }),
      })
      const data = await res.json()
      if (res.ok) {
        setSaveStatus('success'); setSaveMsg(data.message || 'Credentials сохранены')
        setPassword('')
        setTimeout(() => setSaveStatus('idle'), 5000)
      } else {
        setSaveStatus('error'); setSaveMsg(data.detail || 'Ошибка сохранения')
      }
    } catch (e: any) {
      setSaveStatus('error'); setSaveMsg('Ошибка соединения: ' + e.message)
    }
  }

  // ── Test auth ─────────────────────────────────────────────────────
  const testAuth = async () => {
    setAuthStatus('loading'); setAuthMsg('Проверяем авторизацию VK...')
    try {
      const res = await api('/api/admin/vk/test-auth', { method: 'POST' })
      const data = await res.json()
      setAuthStatus(data.success ? 'success' : 'error')
      setAuthMsg(data.message)
    } catch (e: any) {
      setAuthStatus('error'); setAuthMsg('Ошибка запроса: ' + e.message)
    }
  }

  // ── Recreate hashes ───────────────────────────────────────────────
  const recreateHashes = async () => {
    setRecreateStatus('loading'); setRecreateMsg('Создаём хеши, подождите (~15 сек)...')
    try {
      const res = await api('/api/admin/vk/recreate', { method: 'POST' })
      const data = await res.json()
      setRecreateStatus(data.success ? 'success' : 'error')
      setRecreateMsg(data.message)
      if (data.success) setTimeout(fetchHashes, 1000)
    } catch (e: any) {
      setRecreateStatus('error'); setRecreateMsg('Ошибка запроса: ' + e.message)
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold">VK Аккаунт и тоннели</h1>

      {/* ── Credentials ── */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6 space-y-4">
        <div>
          <h2 className="font-semibold flex items-center gap-2 mb-1">
            <Key className="w-4 h-4" /> VK Credentials
          </h2>
          <p className="text-[#555] text-xs">
            AI-ассистент использует этот аккаунт для создания звонков и получения TURN-хешей.
          </p>
        </div>

        <form onSubmit={saveCredentials} className="space-y-3">
          <input
            type="text" value={login} onChange={e => setLogin(e.target.value)}
            placeholder="Логин ВКонтакте (телефон или email)"
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-[#444] transition-colors"
          />
          <div className="relative">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password} onChange={e => setPassword(e.target.value)}
              placeholder="Пароль"
              className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-2.5 pr-11 text-sm text-white focus:outline-none focus:border-[#444] transition-colors"
            />
            <button type="button" onClick={() => setShowPassword(v => !v)} tabIndex={-1}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[#555] hover:text-white transition-colors p-1">
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {/* Save */}
            <button type="submit" disabled={saveStatus === 'loading'}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 ${
                saveStatus === 'success' ? 'bg-green-500 text-white' :
                saveStatus === 'error'   ? 'bg-red-500/20 border border-red-500/50 text-red-400' :
                'bg-white text-black hover:bg-[#e0e0e0]'
              }`}>
              {saveStatus === 'loading' ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Сохраняем...</> :
               saveStatus === 'success' ? <><Check className="w-3.5 h-3.5" /> Сохранено!</> :
               'Сохранить'}
            </button>

            {/* Test auth */}
            <button type="button" onClick={testAuth} disabled={authStatus === 'loading'}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border transition-all disabled:opacity-50 ${
                authStatus === 'success' ? 'bg-green-500/10 border-green-500/40 text-green-400' :
                authStatus === 'error'   ? 'bg-red-500/10 border-red-500/40 text-red-400' :
                'bg-[#1a1a1a] border-[#2a2a2a] text-white hover:border-white'
              }`}>
              {authStatus === 'loading' ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> :
               authStatus === 'success' ? <ShieldCheck className="w-3.5 h-3.5" /> :
               authStatus === 'error'   ? <ShieldX className="w-3.5 h-3.5" /> :
               <ShieldCheck className="w-3.5 h-3.5" />}
              {authStatus === 'loading' ? 'Проверяем...' : 'Проверить авторизацию'}
            </button>
          </div>

          <StatusBadge status={saveStatus} msg={saveMsg} />
          <StatusBadge status={authStatus} msg={authMsg} />
        </form>
      </div>

      {/* ── Hashes ── */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">VK Хеши (TURN туннели)</h2>
          <button onClick={recreateHashes} disabled={recreateStatus === 'loading'}
            className="flex items-center gap-2 bg-[#1a1a1a] border border-[#2a2a2a] px-4 py-2 rounded-lg text-xs hover:border-white transition-colors disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${recreateStatus === 'loading' ? 'animate-spin' : ''}`} />
            {recreateStatus === 'loading' ? 'Создаём...' : 'Пересоздать все'}
          </button>
        </div>

        <StatusBadge status={recreateStatus} msg={recreateMsg} />

        {hashes.length === 0 ? (
          <div className={`text-center py-8 text-[#555] ${recreateStatus !== 'idle' ? 'mt-3' : ''}`}>
            <AlertTriangle className="w-8 h-8 mx-auto mb-2 text-yellow-500" />
            <p className="text-sm">Хеши не созданы.<br/>Сохраните credentials → «Проверить авторизацию» → «Пересоздать все».</p>
          </div>
        ) : (
          <div className={`space-y-2 ${recreateStatus !== 'idle' ? 'mt-3' : ''}`}>
            {hashes.map((h, i) => (
              <div key={h.id ?? i} className="flex items-center gap-3 bg-[#151515] rounded-lg px-4 py-3">
                {h.is_active
                  ? <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
                  : <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />}
                <span className="text-xs text-[#555] w-12 flex-shrink-0">Слот {h.slot}</span>
                <span className="font-mono text-xs flex-1 text-[#ccc] break-all truncate max-w-[220px]">{h.hash}</span>
                <span className="text-xs text-[#555] flex-shrink-0">Сбоев: {h.fail_count}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="bg-[#111] border border-yellow-900/50 rounded-xl p-4">
        <p className="text-xs text-yellow-500/80 leading-relaxed">
          <strong>Порядок настройки:</strong> 1) Введи логин и пароль VK → «Сохранить»
          &nbsp;2) Нажми «Проверить авторизацию» — должно появиться «Успешно»
          &nbsp;3) Нажми «Пересоздать все» для создания TURN-хешей.<br/><br/>
          <strong>Важно:</strong> При звонке ВКонтакте нажимай «Просто завершить»,
          иначе хеш перестанет работать. Монитор проверяет хеши каждые 5 минут.
        </p>
      </div>
    </div>
  )
}
