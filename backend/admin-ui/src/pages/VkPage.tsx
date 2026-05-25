import { useState, useEffect, useRef } from 'react'
import { Key, RefreshCw, CheckCircle, XCircle, AlertTriangle, ShieldCheck, ExternalLink } from 'lucide-react'

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
  const [hashes, setHashes]     = useState<any[]>([])
  const [hasToken, setHasToken] = useState(false)
  const [authStatus, setAuthStatus] = useState<Status>('idle')
  const [authMsg, setAuthMsg]       = useState('')
  const [recreateStatus, setRecreateStatus] = useState<Status>('idle')
  const [recreateMsg, setRecreateMsg]       = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

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

  // ── OAuth popup login ───────────────────────────────────────────────
  const loginViaOAuth = async () => {
    setAuthStatus('loading'); setAuthMsg('Открываем окно авторизации VK...')
    try {
      const res = await api('/api/admin/vk/oauth-url')
      const data = await res.json()
      const popup = window.open(data.url, 'vkAuth', 'width=700,height=600,left=300,top=100')

      if (pollRef.current) clearInterval(pollRef.current)
      setAuthMsg('Авторизуйтесь в открывшемся окне...')

      pollRef.current = setInterval(async () => {
        try {
          const s = await api('/api/admin/vk/oauth-status')
          if (s.ok) {
            const sd = await s.json()
            if (sd.authorized) {
              clearInterval(pollRef.current!)
              setHasToken(true)
              setAuthStatus('success')
              setAuthMsg('Авторизация прошла успешно! Токен привязан к серверу.')
              popup?.close()
            }
          }
        } catch {}
      }, 2000)

      // Close polling after 5 min
      setTimeout(() => {
        clearInterval(pollRef.current!)
        if (authStatus === 'loading') {
          setAuthStatus('idle'); setAuthMsg('')
        }
      }, 300_000)
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

      {/* ── Auth block ── */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6 space-y-4">
        <div>
          <h2 className="font-semibold flex items-center gap-2 mb-1">
            <Key className="w-4 h-4" /> Авторизация ВКонтакте
          </h2>
          <p className="text-[#555] text-xs">
            Войдите через VK OAuth — токен привяжется к IP сервера. Работает с 2FA.
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

        <div className="flex gap-3">
          <button onClick={loginViaOAuth} disabled={authStatus === 'loading'}
            className="flex items-center gap-2 bg-[#4680C2] hover:bg-[#3a6fad] text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
            {authStatus === 'loading'
              ? <><RefreshCw className="w-4 h-4 animate-spin" /> Ожидаем...</>
              : <><ExternalLink className="w-4 h-4" /> {hasToken ? 'Обновить токен VK' : 'Войти через ВКонтакте'}</>}
          </button>
        </div>

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
          1) Нажми «Войти через ВКонтакте» — откроется окно VK&nbsp;
          2) Войди в аккаунт (2FA работает автоматически)&nbsp;
          3) Окно закроется, статус станет зелёным&nbsp;
          4) Нажми «Пересоздать все».<br/><br/>
          <strong>Важно:</strong> При звонке ВКонтакте нажимай «Просто завершить»,
          а не «Завершить для всех» — иначе хеш перестанет работать.
        </p>
      </div>
    </div>
  )
}
