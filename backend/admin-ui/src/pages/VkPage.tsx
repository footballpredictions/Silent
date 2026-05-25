import { useState, useEffect } from 'react'
import { Key, RefreshCw, CheckCircle, XCircle, AlertTriangle, ShieldCheck, Eye, EyeOff } from 'lucide-react'

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
  const [hashes, setHashes] = useState<any[]>([])
  const [hasToken, setHasToken] = useState(false)

  // Login form
  const [login, setLogin]       = useState('')
  const [password, setPassword] = useState('')
  const [showPwd, setShowPwd]   = useState(false)
  const [authStatus, setAuthStatus]   = useState<Status>('idle')
  const [authMsg, setAuthMsg]         = useState('')

  // Recreate
  const [recreateStatus, setRecreateStatus] = useState<Status>('idle')
  const [recreateMsg, setRecreateMsg]       = useState('')

  const api = (path: string, opts?: RequestInit) =>
    fetch(path, { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...opts?.headers }, ...opts })

  const fetchHashes = async () => {
    try {
      const res = await api('/api/admin/vk/hashes')
      if (res.ok) setHashes(await res.json())
    } catch {}
  }

  const fetchStatus = async () => {
    try {
      const res = await api('/api/admin/vk/oauth-status')
      if (res.ok) {
        const data = await res.json()
        setHasToken(data.authorized)
      }
    } catch {}
  }

  useEffect(() => {
    fetchHashes()
    fetchStatus()
  }, [])

  // ── Auth from server ────────────────────────────────────────────────
  const doAuth = async () => {
    if (!login || !password) {
      setAuthStatus('error'); setAuthMsg('Введите логин и пароль VK')
      return
    }
    setAuthStatus('loading'); setAuthMsg('Авторизуемся через сервер...')
    try {
      const res = await api('/api/admin/vk/auth-server', {
        method: 'POST',
        body: JSON.stringify({ login, password }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        setAuthStatus('success')
        setAuthMsg(data.message)
        setHasToken(true)
        setPassword('')
      } else {
        setAuthStatus('error')
        setAuthMsg(data.message || 'Ошибка авторизации')
      }
    } catch (e: any) {
      setAuthStatus('error'); setAuthMsg('Ошибка: ' + e.message)
    }
  }

  // ── Test token ──────────────────────────────────────────────────────
  const testAuth = async () => {
    setAuthStatus('loading'); setAuthMsg('Проверяем токен...')
    try {
      const res = await api('/api/admin/vk/test-auth', { method: 'POST' })
      const data = await res.json()
      setAuthStatus(data.success ? 'success' : 'error')
      setAuthMsg(data.message)
      if (data.success) setHasToken(true)
    } catch (e: any) {
      setAuthStatus('error'); setAuthMsg('Ошибка: ' + e.message)
    }
  }

  // ── Recreate hashes ─────────────────────────────────────────────────
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

      {/* ── Auth form ── */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6 space-y-4">
        <div>
          <h2 className="font-semibold flex items-center gap-2 mb-1">
            <Key className="w-4 h-4" /> Авторизация ВКонтакте
          </h2>
          <p className="text-[#555] text-xs">
            Сервер войдёт в VK с вашего аккаунта напрямую. Токен привяжется к IP сервера.
          </p>
        </div>

        {/* Status indicator */}
        <div className={`flex items-center gap-3 rounded-lg px-4 py-3 border ${
          hasToken ? 'bg-green-500/10 border-green-500/30' : 'bg-[#1a1a1a] border-[#2a2a2a]'
        }`}>
          {hasToken
            ? <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
            : <XCircle    className="w-4 h-4 text-[#555] flex-shrink-0" />}
          <span className={`text-sm ${hasToken ? 'text-green-400' : 'text-[#555]'}`}>
            {hasToken ? 'Аккаунт VK подключён' : 'Аккаунт не подключён'}
          </span>
          {hasToken && (
            <button onClick={testAuth} disabled={authStatus === 'loading'}
              className="ml-auto flex items-center gap-1.5 text-xs text-[#555] hover:text-white transition-colors disabled:opacity-50">
              <ShieldCheck className="w-3.5 h-3.5" />
              {authStatus === 'loading' ? 'Проверяем...' : 'Проверить'}
            </button>
          )}
        </div>

        {/* Login / password */}
        <div className="space-y-2">
          <input
            value={login}
            onChange={e => setLogin(e.target.value)}
            placeholder="Логин VK (телефон или email)"
            className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2.5 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#4680C2] transition-colors"
          />
          <div className="relative">
            <input
              type={showPwd ? 'text' : 'password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && doAuth()}
              placeholder="Пароль VK"
              className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2.5 pr-10 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#4680C2] transition-colors"
            />
            <button type="button" onClick={() => setShowPwd(p => !p)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-[#555] hover:text-white transition-colors">
              {showPwd ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <button onClick={doAuth} disabled={!login || !password || authStatus === 'loading'}
          className="w-full flex items-center justify-center gap-2 bg-[#4680C2] hover:bg-[#3a6fad] text-white py-2.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
          {authStatus === 'loading'
            ? <><RefreshCw className="w-4 h-4 animate-spin" /> Авторизуемся...</>
            : hasToken ? 'Обновить токен' : 'Авторизоваться'}
        </button>

        <StatusBadge status={authStatus} msg={authMsg} />
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
            <p className="text-sm">Хеши не созданы.<br/>Авторизуйтесь выше → «Пересоздать все».</p>
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
          <strong>Порядок настройки:</strong>&nbsp;
          1) Введи логин и пароль VK → «Авторизоваться» (сервер войдёт с своего IP)&nbsp;
          2) Нажми «Пересоздать все» для создания TURN-хешей.<br/><br/>
          <strong>Важно:</strong> При звонке ВКонтакте нажимай «Просто завершить»,
          а не «Завершить для всех» — иначе хеш перестанет работать.
          Монитор проверяет хеши каждые 5 минут.
        </p>
      </div>
    </div>
  )
}
