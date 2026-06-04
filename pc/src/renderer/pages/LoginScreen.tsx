import { useState, useEffect, useMemo } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import api, {
  saveTokens,
  startNewSession,
  saveSessionDeviceId,
  clearSessionFingerprint,
  clearTokens,
  formatApiError,
  getRememberMe,
  getRememberedEmail,
  saveRememberMe,
} from '../api'
import {
  cacheVpnConfig,
  getBootstrapHash,
  saveBootstrapHash,
} from '../vkConfig'
import { extractCallHash } from '../hashConfig'
import {
  ensureBootstrapVpn,
  ensureBootstrapTunnelApi,
  disconnectBootstrapVpn,
  isBootstrapVpnActive,
  prefetchLoginDataViaBootstrap,
  refreshBootstrapSessionTimer,
  setBootstrapStatusListener,
} from '../bootstrapVpn'
import HashInputSection from '../components/HashInputSection'
import SilentLogo from '../components/SilentLogo'
import DebugLogPanel, { DebugLogButton } from '../components/DebugLogPanel'
import TitleBar from '../components/TitleBar'
import { pushLog } from '../debugLog'
import { authStrings as s } from '../authStrings'
import { themeToUi, type ClientTheme } from '../clientTheme'

type LoginStep = 1 | 2 | 'forgot' | 'reset'

export default function LoginScreen({
  theme,
  resetToken,
  onResetDone,
  onLogin,
}: {
  theme: ClientTheme | null
  resetToken?: string | null
  onResetDone?: () => void
  onLogin: (theme: ClientTheme | null) => void
}) {
  const ui = useMemo(() => themeToUi(theme), [theme])

  const [step, setStep] = useState<LoginStep>(1)
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [rememberMe, setRememberMe] = useState(getRememberMe())
  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotSent, setForgotSent] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [resetDone, setResetDone] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [regDone, setRegDone] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const [bootstrapConnecting, setBootstrapConnecting] = useState(false)
  const [bootstrapReady, setBootstrapReady] = useState(isBootstrapVpnActive())
  const [bootstrapHash, setBootstrapHash] = useState<string | null>(getBootstrapHash)
  const [showDebugLog, setShowDebugLog] = useState(false)
  const [fadeIn, setFadeIn] = useState(false)

  const step2Title = theme?.login_step2_title || 'Шаг 2 — вход или регистрация'
  const rememberLabel = theme?.login_remember_me_label || 'Запомнить меня'
  const forgotLabel = theme?.login_forgot_password_label || 'Забыли пароль?'
  const forgotTitle = theme?.login_forgot_title || 'Восстановление пароля'
  const forgotHint = theme?.login_forgot_instruction || 'Введите email — мы отправим ссылку для установки нового пароля.'
  const resetTitle = theme?.login_reset_title || 'Новый пароль'
  const resetBtn = theme?.login_reset_button_text || 'Сохранить пароль'
  const linkColor = theme?.login_link_color || ui.linkColor

  useEffect(() => {
    const saved = getRememberedEmail()
    if (saved) {
      setEmail(saved)
      setRememberMe(true)
    }
  }, [])

  useEffect(() => {
    if (resetToken) {
      setStep('reset')
      setError('')
    }
  }, [resetToken])

  useEffect(() => {
    setBootstrapHash(getBootstrapHash())
    const active = isBootstrapVpnActive()
    setBootstrapReady(active)
    if (active) {
      setStep(2)
      setFadeIn(true)
      refreshBootstrapSessionTimer()
    }
    setBootstrapStatusListener(msg => {
      setStatusMsg(msg)
      setBootstrapReady(isBootstrapVpnActive())
      if (msg.includes('истекло')) {
        setBootstrapHash(getBootstrapHash())
        setStep(1)
        setFadeIn(false)
      }
    })
    return () => setBootstrapStatusListener(null)
  }, [])

  useEffect(() => {
    if (bootstrapReady && step === 1) {
      const t = window.setTimeout(() => {
        setStep(2)
        setFadeIn(true)
      }, 400)
      return () => clearTimeout(t)
    }
  }, [bootstrapReady, step])

  const connectForLogin = async (raw: string) => {
    const h = extractCallHash(raw)
    if (!h) {
      setStatusMsg(s.invalidHash)
      setBootstrapReady(false)
      return
    }
    saveBootstrapHash(h)
    setBootstrapHash(h)
    setBootstrapConnecting(true)
    setBootstrapReady(false)
    setStatusMsg(s.connectingWait)
    setError('')
    try {
      const ok = await ensureBootstrapVpn()
      const active = isBootstrapVpnActive()
      setBootstrapReady(ok && active)
      if (!ok || !active) setBootstrapReady(false)
    } finally {
      setBootstrapConnecting(false)
    }
  }

  const openLoginSession = async (): Promise<{ ok: boolean; subscriptionExpired?: boolean }> => {
    ensureBootstrapTunnelApi()
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
      return { ok: true }
    } catch (e: any) {
      if ((e as any).response?.status === 402) {
        clearSessionFingerprint()
        const msg = (e as any).response?.data?.detail
          ?? 'Пробный период закончился. Оформите подписку.'
        localStorage.setItem('silent_subscription_msg', msg)
        return { ok: false, subscriptionExpired: true }
      }
      clearSessionFingerprint()
      clearTokens()
      setError(formatApiError(e, 'Достигнут лимит устройств (3). Выйдите на другом устройстве.'))
      return { ok: false }
    }
  }

  const finishAuth = async () => {
    saveRememberMe(email, rememberMe)
    const sessionResult = await openLoginSession()
    if (!sessionResult.ok) {
      if (sessionResult.subscriptionExpired) {
        await prefetchLoginDataViaBootstrap().catch(() => false)
        await disconnectBootstrapVpn()
        setBootstrapReady(false)
        const themeRes = await api.get('/api/vpn/theme').catch(() => ({ data: theme }))
        onLogin(themeRes.data ?? theme)
      } else {
        refreshBootstrapSessionTimer()
      }
      return
    }
    await prefetchLoginDataViaBootstrap()
    await disconnectBootstrapVpn()
    setBootstrapReady(false)
    setStatusMsg(s.internetOff)
    const themeRes = await api.get('/api/vpn/theme').catch(() => ({ data: theme }))
    onLogin(themeRes.data ?? theme)
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      if (!isBootstrapVpnActive() || !ensureBootstrapTunnelApi()) {
        setError(s.needBootstrap)
        return
      }
      pushLog('Login', 'auth via tunnel API')
      const res = await api.post('/api/auth/login', { email, password })
      saveTokens(res.data.access_token, res.data.refresh_token)
      await finishAuth()
    } catch (err: any) {
      const msg = formatApiError(err, 'Ошибка входа')
      pushLog('Login', msg, 'E')
      setError(msg)
      refreshBootstrapSessionTimer()
    } finally {
      setLoading(false)
    }
  }

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      if (!isBootstrapVpnActive() || !ensureBootstrapTunnelApi()) {
        setError(s.needBootstrap)
        return
      }
      await api.post('/api/auth/register', { email, password })
      saveRememberMe(email, rememberMe)
      setRegDone(true)
    } catch (err: any) {
      setError(formatApiError(err, 'Ошибка регистрации'))
      refreshBootstrapSessionTimer()
    } finally {
      setLoading(false)
    }
  }

  const handleForgot = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.post('/api/auth/forgot-password', { email: forgotEmail || email })
      setForgotSent(true)
    } catch (err: any) {
      setError(formatApiError(err, 'Ошибка отправки'))
    } finally {
      setLoading(false)
    }
  }

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!resetToken) return
    setLoading(true)
    setError('')
    try {
      await api.post('/api/auth/reset-password', { token: resetToken, new_password: newPassword })
      setResetDone(true)
      onResetDone?.()
    } catch (err: any) {
      setError(formatApiError(err, 'Не удалось сохранить пароль'))
    } finally {
      setLoading(false)
    }
  }

  const fieldCls =
    'w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none transition-colors'

  const passwordField = (
    value: string,
    onChange: (v: string) => void,
    visible: boolean,
    toggle: () => void,
  ) => (
    <div className="relative mb-3">
      <input
        className={fieldCls + ' pr-10'}
        style={{
          background: ui.fieldBg,
          color: ui.fieldText,
          border: `1px solid ${ui.border}`,
        }}
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="••••••••"
        required
        minLength={8}
      />
      <button
        type="button"
        onClick={toggle}
        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 opacity-60 hover:opacity-100"
        style={{ color: ui.fg, background: 'none', border: 'none', cursor: 'pointer' }}
        tabIndex={-1}
      >
        {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  )

  return (
    <div
      className="flex flex-col h-full"
      style={{ background: ui.bg, color: ui.fg, fontFamily: ui.fontFamily }}
    >
      <TitleBar
        title="SILENT VPN"
        headerBg={ui.headerBg}
        headerFg={ui.headerFg}
        right={<DebugLogButton onClick={() => setShowDebugLog(true)} />}
      />

      <div className="flex-1 overflow-y-auto px-5 py-6">
        <div className="flex flex-col items-center mb-5 w-full">
          <SilentLogo size={56} />
          <p className="mt-3 text-base font-bold tracking-[0.3em]" style={{ color: ui.fg }}>
            SILENT VPN
          </p>
        </div>

        {step === 1 && (
          <div className="transition-opacity duration-500 opacity-100">
            <HashInputSection
              bootstrapHash={bootstrapHash}
              statusMsg={statusMsg}
              bootstrapConnecting={bootstrapConnecting}
              bootstrapReady={bootstrapReady}
              onConnect={connectForLogin}
              ui={ui}
              theme={theme}
            />
          </div>
        )}

        {step === 2 && (
          <div
            className="transition-all duration-500"
            style={{ opacity: fadeIn ? 1 : 0, transform: fadeIn ? 'translateY(0)' : 'translateY(12px)' }}
          >
            <p className="text-[13px] font-semibold mb-3" style={{ color: ui.fg }}>
              {step2Title}
            </p>

            <div className="flex rounded-xl p-1 mb-4" style={{ background: ui.tabBg }}>
              {(['login', 'register'] as const).map(key => (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    setTab(key)
                    setError('')
                    if (key === 'login') setRegDone(false)
                  }}
                  className="flex-1 py-2 rounded-[10px] text-xs font-medium transition-colors"
                  style={{
                    background: tab === key ? ui.primaryBtnBg : 'transparent',
                    color: tab === key ? ui.primaryBtnFg : ui.hint,
                  }}
                >
                  {key === 'login' ? s.login : s.register}
                </button>
              ))}
            </div>

            {regDone ? (
              <div className="text-center py-8">
                <p className="font-medium text-sm" style={{ color: ui.fg }}>{s.confirmEmail}</p>
                <p className="text-xs mt-1" style={{ color: ui.hint }}>{s.emailSent(email)}</p>
                <button
                  type="button"
                  onClick={() => { setTab('login'); setRegDone(false) }}
                  className="mt-4 text-xs hover:opacity-80"
                  style={{ color: ui.fg }}
                >
                  {s.login}
                </button>
              </div>
            ) : (
              <form onSubmit={tab === 'login' ? handleLogin : handleRegister}>
                <label className="text-xs" style={{ color: ui.label }}>{s.email}</label>
                <input
                  className={fieldCls + ' mt-1 mb-3'}
                  style={{
                    background: ui.fieldBg,
                    color: ui.fieldText,
                    border: `1px solid ${ui.border}`,
                  }}
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                />
                <label className="text-xs" style={{ color: ui.label }}>{s.password}</label>
                {passwordField(password, setPassword, showPassword, () => setShowPassword(v => !v))}
                <div className="flex items-center justify-between mb-3 text-xs">
                  <label className="flex items-center gap-2 cursor-pointer" style={{ color: ui.hint }}>
                    <input
                      type="checkbox"
                      checked={rememberMe}
                      onChange={e => setRememberMe(e.target.checked)}
                      className="rounded"
                    />
                    {rememberLabel}
                  </label>
                  {tab === 'login' && (
                    <button
                      type="button"
                      onClick={() => { setForgotEmail(email); setStep('forgot'); setError(''); setForgotSent(false) }}
                      className="hover:opacity-80"
                      style={{ color: linkColor, background: 'none', border: 'none', cursor: 'pointer' }}
                    >
                      {forgotLabel}
                    </button>
                  )}
                </div>
                {error && (
                  <p className="text-xs mb-2" style={{ color: ui.red }}>{error}</p>
                )}
                <button
                  type="submit"
                  disabled={loading || !email.trim() || !password.trim()}
                  className="w-full py-3 rounded-xl text-sm font-semibold disabled:opacity-40"
                  style={{ background: ui.primaryBtnBg, color: ui.primaryBtnFg }}
                >
                  {loading ? '…' : tab === 'login' ? s.login : s.registerSubmit}
                </button>
                <button
                  type="button"
                  onClick={() => { setStep(1); setFadeIn(false) }}
                  className="w-full mt-3 text-xs opacity-60 hover:opacity-100"
                  style={{ color: ui.fg, background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  ← Изменить хеш VK
                </button>
              </form>
            )}
          </div>
        )}

        {step === 'forgot' && (
          <div>
            <p className="text-sm font-semibold mb-2" style={{ color: ui.fg }}>{forgotTitle}</p>
            <p className="text-xs mb-4 leading-relaxed" style={{ color: ui.hint }}>{forgotHint}</p>
            {forgotSent ? (
              <p className="text-xs text-center py-6" style={{ color: ui.green }}>
                Если email зарегистрирован, письмо отправлено. Откройте ссылку в письме.
              </p>
            ) : (
              <form onSubmit={handleForgot}>
                <label className="text-xs" style={{ color: ui.label }}>{s.email}</label>
                <input
                  className={fieldCls + ' mt-1 mb-3'}
                  style={{
                    background: ui.fieldBg,
                    color: ui.fieldText,
                    border: `1px solid ${ui.border}`,
                  }}
                  type="email"
                  value={forgotEmail}
                  onChange={e => setForgotEmail(e.target.value)}
                  required
                />
                {error && <p className="text-xs mb-2" style={{ color: ui.red }}>{error}</p>}
                <button
                  type="submit"
                  disabled={loading || !forgotEmail.trim()}
                  className="w-full py-3 rounded-xl text-sm font-semibold disabled:opacity-40"
                  style={{ background: ui.primaryBtnBg, color: ui.primaryBtnFg }}
                >
                  {loading ? '…' : 'Отправить письмо'}
                </button>
              </form>
            )}
            <button
              type="button"
              onClick={() => { setStep(bootstrapReady ? 2 : 1); setError('') }}
              className="w-full mt-4 text-xs opacity-60 hover:opacity-100"
              style={{ color: ui.fg, background: 'none', border: 'none', cursor: 'pointer' }}
            >
              ← Назад
            </button>
          </div>
        )}

        {step === 'reset' && (
          <div>
            <p className="text-sm font-semibold mb-2" style={{ color: ui.fg }}>{resetTitle}</p>
            {resetDone ? (
              <div className="text-center py-6">
                <p className="text-sm font-medium" style={{ color: ui.green }}>Пароль сохранён</p>
                <button
                  type="button"
                  onClick={() => { setStep(bootstrapReady ? 2 : 1); setResetDone(false); setNewPassword('') }}
                  className="mt-4 text-xs"
                  style={{ color: ui.fg }}
                >
                  {s.login}
                </button>
              </div>
            ) : (
              <form onSubmit={handleResetPassword}>
                <label className="text-xs" style={{ color: ui.label }}>{s.password}</label>
                {passwordField(newPassword, setNewPassword, showNewPassword, () => setShowNewPassword(v => !v))}
                {error && <p className="text-xs mb-2" style={{ color: ui.red }}>{error}</p>}
                <button
                  type="submit"
                  disabled={loading || newPassword.length < 8}
                  className="w-full py-3 rounded-xl text-sm font-semibold disabled:opacity-40"
                  style={{ background: ui.primaryBtnBg, color: ui.primaryBtnFg }}
                >
                  {loading ? '…' : resetBtn}
                </button>
              </form>
            )}
          </div>
        )}
      </div>
      <DebugLogPanel open={showDebugLog} onClose={() => setShowDebugLog(false)} />
    </div>
  )
}
