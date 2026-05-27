import { useState, useEffect } from 'react'
import api, {
  saveTokens,
  startNewSession,
  saveSessionDeviceId,
  clearSessionFingerprint,
  clearTokens,
  formatApiError,
} from '../api'
import {
  cacheVpnConfig,
  getBootstrapHash,
  saveBootstrapHash,
} from '../vkConfig'
import { extractCallHash } from '../hashConfig'
import {
  ensureBootstrapVpn,
  disconnectBootstrapVpn,
  isBootstrapVpnActive,
} from '../bootstrapVpn'
import HashInputSection from '../components/HashInputSection'
import SilentLogo from '../components/SilentLogo'
import DebugLogPanel, { DebugLogButton } from '../components/DebugLogPanel'
import { pushLog } from '../debugLog'

export default function LoginScreen({ onLogin }: { onLogin: (theme: any) => void }) {
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [regDone, setRegDone] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const [bootstrapConnecting, setBootstrapConnecting] = useState(false)
  const [bootstrapHash, setBootstrapHash] = useState<string | null>(getBootstrapHash)
  const [showDebugLog, setShowDebugLog] = useState(false)

  useEffect(() => {
    setBootstrapHash(getBootstrapHash())
  }, [])

  const connectForLogin = async (raw: string) => {
    const h = extractCallHash(raw)
    if (!h) {
      setStatusMsg('Неверный хеш. Вставьте ссылку vk.com/call/join/… или сам хеш')
      return
    }
    saveBootstrapHash(h)
    setBootstrapHash(h)
    setBootstrapConnecting(true)
    setStatusMsg('')
    setError('')
    try {
      const ok = await ensureBootstrapVpn()
      setStatusMsg(
        ok
          ? 'Канал готов. Можно войти или зарегистрироваться.'
          : 'Не удалось получить bootstrap-конфиг или подключиться',
      )
    } finally {
      setBootstrapConnecting(false)
    }
  }

  const openLoginSession = async (): Promise<boolean> => {
    const fp = startNewSession()
    const boot = getBootstrapHash()
    try {
      const reg = await api.post('/api/vpn/device/register', {
        device_name: 'PC',
        device_type: 'pc',
        device_fingerprint: fp,
        bootstrap_hash: boot || undefined,
      })
      saveSessionDeviceId(reg.data.device_id)
      cacheVpnConfig(reg.data)
      return true
    } catch (e: any) {
      clearSessionFingerprint()
      clearTokens()
      setError(formatApiError(e, 'Достигнут лимит устройств (3). Выйдите на другом устройстве.'))
      return false
    }
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      if (!isBootstrapVpnActive()) {
        setError('Сначала нажмите «Подключить для входа»')
        return
      }
      const res = await api.post('/api/auth/login', { email, password })
      saveTokens(res.data.access_token, res.data.refresh_token)
      if (!(await openLoginSession())) return
      await disconnectBootstrapVpn()
      setStatusMsg('Интернет отключён. VPN включайте на главном экране.')
      const themeRes = await api.get('/api/vpn/theme').catch(() => ({ data: null }))
      onLogin(themeRes.data)
    } catch (err: any) {
      const msg = formatApiError(err, 'Ошибка входа')
      pushLog('Login', msg, 'E')
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.post('/api/auth/register', { email, password })
      setRegDone(true)
    } catch (err: any) {
      setError(formatApiError(err, 'Ошибка регистрации'))
    } finally {
      setLoading(false)
    }
  }

  const inputCls =
    'w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-black transition-colors'

  return (
    <div className="flex flex-col h-full">
      <div
        className="h-8 bg-black flex items-center px-4 flex-shrink-0"
        style={{ WebkitAppRegion: 'drag' } as any}
      >
        <span className="text-xs text-gray-500 tracking-widest">SILENT VPN</span>
        <div className="ml-auto flex items-center gap-2" style={{ WebkitAppRegion: 'no-drag' } as any}>
          <DebugLogButton onClick={() => setShowDebugLog(true)} />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-6">
        <div className="flex flex-col items-center mb-5">
          <SilentLogo size={56} />
          <p className="mt-3 text-base font-bold tracking-[0.3em]">SILENT</p>
        </div>

        <HashInputSection
          bootstrapHash={bootstrapHash}
          statusMsg={statusMsg}
          bootstrapConnecting={bootstrapConnecting}
          onConnect={connectForLogin}
        />

        <div className="flex bg-gray-100 rounded-xl p-1 mb-4">
          {(['login', 'register'] as const).map(key => (
            <button
              key={key}
              type="button"
              onClick={() => {
                setTab(key)
                setError('')
              }}
              className={`flex-1 py-2 rounded-lg text-xs font-medium transition-colors ${
                tab === key ? 'bg-black text-white' : 'text-gray-500'
              }`}
            >
              {key === 'login' ? 'Войти' : 'Регистрация'}
            </button>
          ))}
        </div>

        {regDone ? (
          <div className="text-center py-8">
            <p className="font-medium text-sm">Подтвердите email</p>
            <p className="text-xs text-gray-500 mt-1">Ссылка отправлена на {email}</p>
          </div>
        ) : (
          <form onSubmit={tab === 'login' ? handleLogin : handleRegister}>
            <label className="text-xs text-gray-500">Email</label>
            <input
              className={inputCls + ' mt-1 mb-3'}
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
            />
            <label className="text-xs text-gray-500">Пароль</label>
            <input
              className={inputCls + ' mt-1 mb-3'}
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
            />
            {error && <p className="text-xs text-red-500 mb-2">{error}</p>}
            <button
              type="submit"
              disabled={loading || !email.trim() || !password.trim()}
              className="w-full py-3 bg-black text-white rounded-xl text-sm font-semibold disabled:opacity-40"
            >
              {loading ? '…' : tab === 'login' ? 'Войти' : 'Зарегистрироваться'}
            </button>
          </form>
        )}
      </div>
      <DebugLogPanel open={showDebugLog} onClose={() => setShowDebugLog(false)} />
    </div>
  )
}
