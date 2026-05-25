import { useState, useEffect, useRef } from 'react'
import { Key, RefreshCw, CheckCircle, XCircle, AlertTriangle, ShieldCheck, ShieldX, ExternalLink } from 'lucide-react'

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
  const [oauthAuthorized, setOauthAuthorized] = useState(false)
  const [authStatus, setAuthStatus]     = useState<Status>('idle')
  const [authMsg, setAuthMsg]           = useState('')
  const [recreateStatus, setRecreateStatus] = useState<Status>('idle')
  const [recreateMsg, setRecreateMsg]   = useState('')
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const api = (path: string, opts?: RequestInit) =>
    fetch(path, { headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...opts?.headers }, ...opts })

  const fetchHashes = async () => {
    try {
      const res = await api('/api/admin/vk/hashes')
      if (res.ok) setHashes(await res.json())
    } catch {}
  }

  const fetchOauthStatus = async () => {
    try {
      const res = await api('/api/admin/vk/oauth-status')
      if (res.ok) {
        const data = await res.json()
        setOauthAuthorized(data.authorized)
      }
    } catch {}
  }

  useEffect(() => {
    fetchHashes()
    fetchOauthStatus()
  }, [])

  // ── VK Token via browser ─────────────────────────────────────────
  const [tokenInput, setTokenInput] = useState('')
  const [showTokenInput, setShowTokenInput] = useState(false)
  const [saveTokenStatus, setSaveTokenStatus] = useState<Status>('idle')
  const [saveTokenMsg, setSaveTokenMsg] = useState('')

  const VK_AUTH_URL = 'https://oauth.vk.com/authorize?client_id=6287487&scope=offline&redirect_uri=https://oauth.vk.com/blank.html&display=page&response_type=token'

  const openVkAuth = () => {
    window.open(VK_AUTH_URL, '_blank')
    setShowTokenInput(true)
  }

  const extractToken = (input: string): string => {
    // Support pasting full URL or just the token
    const match = input.match(/access_token=([A-Za-z0-9_\-.]+)/)
    if (match) return match[1]
    // Or plain token string
    if (/^[A-Za-z0-9_\-.]{30,}$/.test(input.trim())) return input.trim()
    return ''
  }

  const saveToken = async () => {
    const tk = extractToken(tokenInput)
    if (!tk) {
      setSaveTokenStatus('error')
      setSaveTokenMsg('Не найден токен. Скопируй адресную строку полностью.')
      return
    }
    setSaveTokenStatus('loading'); setSaveTokenMsg('Сохраняем...')
    try {
      const res = await api('/api/admin/vk/save-token', {
        method: 'POST', body: JSON.stringify({ token: tk }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        setSaveTokenStatus('success')
        setSaveTokenMsg('Токен сохранён! Теперь нажмите «Пересоздать все».')
        setOauthAuthorized(true)
        setTokenInput('')
        setShowTokenInput(false)
        setTimeout(() => setSaveTokenStatus('idle'), 6000)
      } else {
        setSaveTokenStatus('error'); setSaveTokenMsg(data.message || 'Ошибка сохранения')
      }
    } catch (e: any) {
      setSaveTokenStatus('error'); setSaveTokenMsg('Ошибка: ' + e.message)
    }
  }

  const loginViaOAuth = openVkAuth

  // ── Test existing token ───────────────────────────────────────────
  const testAuth = async () => {
    setAuthStatus('loading'); setAuthMsg('Проверяем токен VK...')
    try {
      const res = await api('/api/admin/vk/test-auth', { method: 'POST' })
      const data = await res.json()
      setAuthStatus(data.success ? 'success' : 'error')
      setAuthMsg(data.message)
      if (data.success) setOauthAuthorized(true)
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

      {/* ── OAuth Login ── */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-6 space-y-4">
        <div>
          <h2 className="font-semibold flex items-center gap-2 mb-1">
            <Key className="w-4 h-4" /> Авторизация ВКонтакте
          </h2>
          <p className="text-[#555] text-xs">
            Войдите в аккаунт VK через браузер. Работает с любым аккаунтом, включая 2FA.
          </p>
        </div>

        {/* Status indicator */}
        <div className={`flex items-center gap-3 rounded-lg px-4 py-3 border ${
          oauthAuthorized
            ? 'bg-green-500/10 border-green-500/30'
            : 'bg-[#1a1a1a] border-[#2a2a2a]'
        }`}>
          {oauthAuthorized
            ? <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0" />
            : <XCircle className="w-4 h-4 text-[#555] flex-shrink-0" />}
          <span className={`text-sm ${oauthAuthorized ? 'text-green-400' : 'text-[#555]'}`}>
            {oauthAuthorized ? 'Аккаунт VK подключён' : 'Аккаунт не подключён'}
          </span>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <button onClick={openVkAuth}
            className="flex items-center gap-2 bg-[#4680C2] hover:bg-[#3a6fad] text-white px-5 py-2.5 rounded-lg text-sm font-semibold transition-colors">
            <ExternalLink className="w-3.5 h-3.5" />
            {oauthAuthorized ? 'Обновить токен VK' : 'Получить токен VK'}
          </button>

          {oauthAuthorized && (
            <button onClick={testAuth} disabled={authStatus === 'loading'}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold border transition-all disabled:opacity-50 ${
                authStatus === 'success' ? 'bg-green-500/10 border-green-500/40 text-green-400' :
                authStatus === 'error'   ? 'bg-red-500/10 border-red-500/40 text-red-400' :
                'bg-[#1a1a1a] border-[#2a2a2a] text-white hover:border-white'
              }`}>
              {authStatus === 'loading' ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" /> Проверяем...</>
               : authStatus === 'success' ? <><ShieldCheck className="w-3.5 h-3.5" /> Токен валиден</>
               : <><ShieldCheck className="w-3.5 h-3.5" /> Проверить токен</>}
            </button>
          )}
        </div>

        {/* Step-by-step instruction + token paste */}
        {showTokenInput && (
          <div className="bg-[#0d0d0d] border border-[#2a2a2a] rounded-xl p-4 space-y-3">
            <p className="text-xs text-[#aaa] leading-relaxed">
              <span className="text-white font-semibold">Шаг 1.</span> В открывшейся вкладке войди в ВКонтакте.<br/>
              <span className="text-white font-semibold">Шаг 2.</span> После входа ты увидишь <em>пустую белую страницу</em> — это нормально.<br/>
              <span className="text-white font-semibold">Шаг 3.</span> Скопируй <strong>весь адрес</strong> из адресной строки браузера.<br/>
              <span className="text-[#555]">Пример: <code className="text-[#888]">https://oauth.vk.com/blank.html#access_token=vk1.a.Abc123...</code></span>
            </p>
            <div className="flex gap-2">
              <input
                value={tokenInput}
                onChange={e => setTokenInput(e.target.value)}
                placeholder="Вставь URL или токен сюда..."
                className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2.5 text-xs text-white focus:outline-none focus:border-[#4680C2] transition-colors"
              />
              <button onClick={saveToken} disabled={!tokenInput || saveTokenStatus === 'loading'}
                className="px-4 py-2.5 bg-[#4680C2] hover:bg-[#3a6fad] text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50">
                {saveTokenStatus === 'loading' ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Сохранить'}
              </button>
            </div>
            <StatusBadge status={saveTokenStatus} msg={saveTokenMsg} />
          </div>
        )}

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
          <strong>Порядок настройки:</strong>&nbsp;
          1) Нажми «Войти через ВКонтакте» — откроется новая вкладка&nbsp;
          2) Войди в свой аккаунт VK и подтверди доступ&nbsp;
          3) Вкладка закроется автоматически, статус сменится на зелёный&nbsp;
          4) Нажми «Пересоздать все» для создания TURN-хешей.<br/><br/>
          <strong>Важно:</strong> При звонке ВКонтакте нажимай «Просто завершить»,
          а не «Завершить для всех» — иначе хеш перестанет работать.
          Монитор проверяет хеши каждые 5 минут.
        </p>
      </div>
    </div>
  )
}
