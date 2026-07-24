import { useEffect, useState } from 'react'
import SilentLogo from '../components/SilentLogo'

const LOGIN_KEY = 'admin_login_remembered'
const DEVICE_KEY = 'admin_device_token'
const FP_KEY = 'admin_device_fp'
const PHONE_MODEL_KEY = 'admin_phone_model'
const MFA_TTL_DEFAULT = 600

type DeviceInfo = {
  device_fingerprint: string
  device_type: 'phone' | 'pc' | 'tablet'
  device_name: string
  client_platform: string
  client_mobile: boolean
}

function getOrCreateFingerprint(): string {
  let fp = localStorage.getItem(FP_KEY)
  if (!fp) {
    fp = (crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`)
    localStorage.setItem(FP_KEY, fp)
  }
  return fp
}

function parseAndroidModelFromUa(ua: string): string {
  const m = ua.match(/Android\s+[\d.]+;\s*([^;)]+)/i)
  if (!m) return ''
  const model = m[1].trim()
  if (!model || model === 'K' || /^Linux/i.test(model) || model.length < 2) return ''
  return model
}

function formatPhoneDisplayName(model: string): string {
  const raw = model.trim()
  if (!raw) return ''
  let name = raw
  if (/^SM-|GT-/i.test(raw) && !/^Samsung\s/i.test(raw)) name = `Samsung ${raw}`
  else if (/^Pixel/i.test(raw) && !/^Google\s/i.test(raw)) name = `Google ${raw}`
  return (name.charAt(0).toUpperCase() + name.slice(1)).slice(0, 64)
}

function isGenericPhoneName(name: string): boolean {
  return !name || ['телефон', 'планшет', 'android', 'mobile', 'k'].includes(name.trim().toLowerCase())
}

async function detectPhoneModel(): Promise<string> {
  const ua = navigator.userAgent || ''
  let model = ''
  try {
    const uad = (navigator as Navigator & {
      userAgentData?: {
        getHighEntropyValues?: (h: string[]) => Promise<{ model?: string; platform?: string }>
      }
    }).userAgentData
    if (uad?.getHighEntropyValues) {
      const he = await uad.getHighEntropyValues(['model', 'platform', 'platformVersion'])
      model = (he.model || '').trim()
      if (model === 'K') model = ''
    }
  } catch {
    /* ignore */
  }
  if (!model) model = parseAndroidModelFromUa(ua)
  // Some WebViews put model elsewhere
  if (!model) {
    const m2 = ua.match(/;\s*([A-Z]{2,}-[A-Z0-9]+)\s*(?:Build|\))/i)
    if (m2) model = m2[1]
  }
  return formatPhoneDisplayName(model)
}

async function getDeviceInfo(phoneModelOverride?: string): Promise<DeviceInfo> {
  const fingerprint = getOrCreateFingerprint()
  const ua = navigator.userAgent || ''
  const touch =
    (navigator.maxTouchPoints || 0) > 1 ||
    (typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches)

  let platform = ''
  let mobile = false
  try {
    const uad = (navigator as Navigator & {
      userAgentData?: {
        platform?: string
        mobile?: boolean
        getHighEntropyValues?: (h: string[]) => Promise<{ platform?: string; model?: string }>
      }
    }).userAgentData
    if (uad) {
      platform = uad.platform || ''
      mobile = !!uad.mobile
      if (uad.getHighEntropyValues) {
        const he = await uad.getHighEntropyValues(['platform', 'model'])
        platform = he.platform || platform
      }
    }
  } catch {
    /* ignore */
  }

  const isAndroid =
    /Android/i.test(ua) ||
    mobile ||
    platform.toLowerCase() === 'android' ||
    (touch && /linux/i.test(platform + ' ' + ua) && !/Windows|Macintosh/i.test(ua))

  const isIOS = /iPhone|iPad|iPod/i.test(ua) || platform.toLowerCase() === 'ios'
  const isIPad = /iPad/i.test(ua) || (isIOS && touch && (navigator.maxTouchPoints || 0) > 1)

  if (isAndroid || (touch && !/Windows|Macintosh/i.test(ua) && !isIOS)) {
    const detected = await detectPhoneModel()
    const saved = (localStorage.getItem(PHONE_MODEL_KEY) || '').trim()
    const override = (phoneModelOverride || '').trim()
    const device_name =
      formatPhoneDisplayName(override) ||
      detected ||
      formatPhoneDisplayName(saved) ||
      'Телефон'
    return {
      device_fingerprint: fingerprint,
      device_type: 'phone',
      device_name,
      client_platform: 'Android',
      client_mobile: true,
    }
  }
  if (isIOS) {
    const detected = await detectPhoneModel()
    const saved = (localStorage.getItem(PHONE_MODEL_KEY) || '').trim()
    const override = (phoneModelOverride || '').trim()
    const device_name =
      formatPhoneDisplayName(override) ||
      detected ||
      formatPhoneDisplayName(saved) ||
      (isIPad ? 'iPad' : 'iPhone')
    return {
      device_fingerprint: fingerprint,
      device_type: isIPad ? 'tablet' : 'phone',
      device_name,
      client_platform: 'iOS',
      client_mobile: true,
    }
  }
  if (/Windows/i.test(ua) || platform.toLowerCase() === 'windows') {
    return {
      device_fingerprint: fingerprint,
      device_type: 'pc',
      device_name: 'ПК',
      client_platform: 'Windows',
      client_mobile: false,
    }
  }
  if (/Mac OS|Macintosh/i.test(ua) || /mac/i.test(platform)) {
    return {
      device_fingerprint: fingerprint,
      device_type: 'pc',
      device_name: 'ПК',
      client_platform: 'macOS',
      client_mobile: false,
    }
  }
  return {
    device_fingerprint: fingerprint,
    device_type: 'pc',
    device_name: 'ПК',
    client_platform: platform || 'Linux',
    client_mobile: false,
  }
}

function MonoCheckbox({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`shrink-0 w-4 h-4 rounded border flex items-center justify-center transition-colors ${
        checked
          ? 'bg-white border-white'
          : 'bg-[#1a1a1a] border-[#444] hover:border-[#888]'
      }`}
    >
      {checked && (
        <svg viewBox="0 0 12 12" className="w-2.5 h-2.5 text-black" aria-hidden>
          <path
            d="M2 6.2L4.8 9 10 3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  )
}

function EyeIcon({ open }: { open: boolean }) {
  if (open) {
    return (
      <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.6">
        <path d="M3 12s3.5-7 9-7 9 7 9 7-3.5 7-9 7-9-7-9-7Z" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="2.5" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M3 12s3.5-7 9-7 9 7 9 7-3.5 7-9 7-9-7-9-7Z" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 4l16 16" strokeLinecap="round" />
    </svg>
  )
}

function formatMmSs(total: number): string {
  const s = Math.max(0, Math.floor(total))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${r.toString().padStart(2, '0')}`
}

export default function LoginPage({ onLogin }: { onLogin: (token: string) => void }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [rememberLogin, setRememberLogin] = useState(true)
  const [rememberDevice, setRememberDevice] = useState(true)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [challengeId, setChallengeId] = useState<string | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  const [mfaSecondsLeft, setMfaSecondsLeft] = useState(0)
  const [resending, setResending] = useState(false)
  const [needPhoneModel, setNeedPhoneModel] = useState(false)
  const [phoneModel, setPhoneModel] = useState(() => (localStorage.getItem(PHONE_MODEL_KEY) || '').trim())

  useEffect(() => {
    const saved = localStorage.getItem(LOGIN_KEY)
    if (saved) {
      setLogin(saved)
      setRememberLogin(true)
    }
    ;(async () => {
      const d = await getDeviceInfo()
      if (d.device_type === 'phone' || d.device_type === 'tablet') {
        if (!isGenericPhoneName(d.device_name)) {
          setPhoneModel(d.device_name)
          localStorage.setItem(PHONE_MODEL_KEY, d.device_name)
          setNeedPhoneModel(false)
        } else {
          setNeedPhoneModel(true)
        }
      } else {
        setNeedPhoneModel(false)
      }
    })()
  }, [])

  useEffect(() => {
    if (!challengeId) return
    const t = window.setInterval(() => {
      setMfaSecondsLeft(prev => (prev <= 1 ? 0 : prev - 1))
    }, 1000)
    return () => window.clearInterval(t)
  }, [challengeId])

  const finishLogin = (accessToken: string, deviceToken?: string | null) => {
    if (rememberLogin) localStorage.setItem(LOGIN_KEY, login)
    else localStorage.removeItem(LOGIN_KEY)
    if (deviceToken) localStorage.setItem(DEVICE_KEY, deviceToken)
    else if (!rememberDevice) localStorage.removeItem(DEVICE_KEY)
    if (needPhoneModel && phoneModel.trim()) {
      localStorage.setItem(PHONE_MODEL_KEY, phoneModel.trim().slice(0, 64))
    }
    onLogin(accessToken)
  }

  const startMfa = (id: string, ttl?: number | null) => {
    setChallengeId(id)
    setMfaCode('')
    setMfaSecondsLeft(typeof ttl === 'number' && ttl > 0 ? ttl : MFA_TTL_DEFAULT)
    setError('')
  }

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (needPhoneModel && !phoneModel.trim()) {
      setError('Укажите модель телефона (например Samsung SM-S911B)')
      return
    }
    setLoading(true)
    setError('')
    try {
      if (needPhoneModel && phoneModel.trim()) {
        localStorage.setItem(PHONE_MODEL_KEY, phoneModel.trim().slice(0, 64))
      }
      const device = await getDeviceInfo(phoneModel)
      const res = await fetch('/api/auth/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          login,
          password,
          device_token: localStorage.getItem(DEVICE_KEY),
          remember_device: rememberDevice,
          ...device,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Неверные данные')
      if (data.requires_mfa && data.challenge_id) {
        startMfa(data.challenge_id, data.mfa_ttl_seconds)
        return
      }
      if (!data.access_token) throw new Error('Нет токена')
      finishLogin(data.access_token, data.device_token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Неверный логин или пароль')
    } finally {
      setLoading(false)
    }
  }

  const handleMfaSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!challengeId) return
    if (mfaSecondsLeft <= 0) {
      setError('Время кода истекло. Запросите новый.')
      return
    }
    setLoading(true)
    setError('')
    try {
      const device = await getDeviceInfo(phoneModel)
      const res = await fetch('/api/auth/admin/mfa/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          challenge_id: challengeId,
          code: mfaCode.trim(),
          remember_device: rememberDevice,
          device_token: localStorage.getItem(DEVICE_KEY),
          ...device,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Неверный код')
      if (!data.access_token) throw new Error('Нет токена')
      finishLogin(data.access_token, data.device_token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка подтверждения')
    } finally {
      setLoading(false)
    }
  }

  const handleMfaResend = async () => {
    if (!challengeId || mfaSecondsLeft > 0 || resending) return
    setResending(true)
    setError('')
    try {
      const res = await fetch('/api/auth/admin/mfa/resend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ challenge_id: challengeId }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Не удалось отправить код')
      if (!data.challenge_id) throw new Error('Нет challenge_id')
      startMfa(data.challenge_id, data.mfa_ttl_seconds)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка отправки')
    } finally {
      setResending(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex mb-4">
            <SilentLogo size={64} />
          </div>
          <h1 className="text-2xl font-bold">Silent VPN</h1>
          <p className="text-[#555] text-sm mt-1">Админ панель</p>
        </div>

        {!challengeId ? (
          <form onSubmit={handlePasswordSubmit} className="bg-[#111] border border-[#222] rounded-2xl p-6 space-y-4">
            <div>
              <label className="block text-xs text-[#888] mb-1.5 uppercase tracking-wider">Логин</label>
              <input
                type="text"
                value={login}
                onChange={e => setLogin(e.target.value)}
                className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-3 text-white text-sm focus:outline-none focus:border-white transition-colors"
                placeholder="admin"
                required
                autoComplete="username"
              />
            </div>
            <div>
              <label className="block text-xs text-[#888] mb-1.5 uppercase tracking-wider">Пароль</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-3 pr-12 text-white text-sm focus:outline-none focus:border-white transition-colors"
                  placeholder="••••••••"
                  required
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(v => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#666] hover:text-white transition-colors"
                  aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                  tabIndex={-1}
                >
                  <EyeIcon open={showPassword} />
                </button>
              </div>
            </div>

            {needPhoneModel && (
              <div>
                <label className="block text-xs text-[#888] mb-1.5 uppercase tracking-wider">
                  Модель телефона
                </label>
                <input
                  type="text"
                  value={phoneModel}
                  onChange={e => setPhoneModel(e.target.value.slice(0, 64))}
                  className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-3 text-white text-sm focus:outline-none focus:border-white transition-colors"
                  placeholder="Samsung Galaxy S23"
                  required
                  autoComplete="off"
                />
                <p className="text-[11px] text-[#555] mt-1.5 leading-snug">
                  Браузер скрыл модель — укажите один раз, сохранится на этом устройстве.
                </p>
              </div>
            )}

            <label className="flex items-center gap-2.5 text-sm text-[#888] cursor-pointer select-none">
              <MonoCheckbox checked={rememberLogin} onChange={setRememberLogin} />
              Запомнить логин
            </label>
            <label className="flex items-center gap-2.5 text-sm text-[#888] cursor-pointer select-none">
              <MonoCheckbox checked={rememberDevice} onChange={setRememberDevice} />
              Запомнить это устройство
            </label>

            {error && (
              <p className="text-red-400 text-sm text-center">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-white text-black rounded-lg py-3 font-semibold text-sm hover:bg-[#e0e0e0] disabled:opacity-50 transition-colors mt-2"
            >
              {loading ? 'Входим...' : 'Войти'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleMfaSubmit} className="bg-[#111] border border-[#222] rounded-2xl p-6 space-y-4">
            <p className="text-sm text-[#aaa] text-center leading-relaxed">
              Код отправлен на почту администратора. Введите его в течение 10 минут.
            </p>
            <div>
              <label className="block text-xs text-[#888] mb-1.5 uppercase tracking-wider">Код из письма</label>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={6}
                value={mfaCode}
                onChange={e => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-4 py-3 text-white text-center text-2xl tracking-[0.4em] font-mono focus:outline-none focus:border-white transition-colors"
                placeholder="000000"
                required
                autoFocus
                disabled={mfaSecondsLeft <= 0}
              />
            </div>
            <p className="text-center text-sm text-[#666]">
              {mfaSecondsLeft > 0 ? (
                <>Код действует ещё <span className="text-white font-mono">{formatMmSs(mfaSecondsLeft)}</span></>
              ) : (
                <span className="text-[#aaa]">Время истекло — запросите новый код</span>
              )}
            </p>
            <label className="flex items-center gap-2.5 text-sm text-[#888] cursor-pointer select-none">
              <MonoCheckbox checked={rememberDevice} onChange={setRememberDevice} />
              Запомнить это устройство
            </label>
            {error && (
              <p className="text-red-400 text-sm text-center">{error}</p>
            )}
            <button
              type="submit"
              disabled={loading || mfaCode.length < 6 || mfaSecondsLeft <= 0}
              className="w-full bg-white text-black rounded-lg py-3 font-semibold text-sm hover:bg-[#e0e0e0] disabled:opacity-50 transition-colors"
            >
              {loading ? 'Проверяем...' : 'Подтвердить'}
            </button>
            <button
              type="button"
              onClick={handleMfaResend}
              disabled={mfaSecondsLeft > 0 || resending}
              className="w-full text-sm py-1 transition-colors disabled:text-[#444] disabled:cursor-not-allowed text-[#aaa] hover:text-white"
            >
              {resending ? 'Отправляем...' : mfaSecondsLeft > 0 ? `Повторная отправка через ${formatMmSs(mfaSecondsLeft)}` : 'Отправить код снова'}
            </button>
            <button
              type="button"
              onClick={() => { setChallengeId(null); setMfaCode(''); setError(''); setMfaSecondsLeft(0) }}
              className="w-full text-[#666] text-sm hover:text-white transition-colors py-1"
            >
              Назад
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
