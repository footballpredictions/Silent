import { useState, useEffect, useMemo } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import api, {
  saveTokens,
  startNewSession,
  saveSessionDeviceId,
  clearSessionFingerprint,
  clearTokens,
  isLoggedIn,
  formatApiError,
  getRememberMe,
  getRememberedEmail,
  getRememberedPassword,
  saveRememberMe,
} from '../api'
import {
  cacheVpnConfig,
  getBootstrapHash,
} from '../vkConfig'
import {
  ensureBootstrapVpn,
  disconnectBootstrapVpn,
  isBootstrapExpired,
  isBootstrapVpnActive,
  prefetchLoginDataViaBootstrap,
  resetBootstrapRendererState,
  shutdownBootstrapBeforeExit,
  setBootstrapStatusListener,
} from '../bootstrapVpn'
import LoginExpiredPanel from '../components/LoginExpiredPanel'
import ThemeCheckbox from '../components/ThemeCheckbox'
import SilentLogo from '../components/SilentLogo'
import DebugLogPanel, { DebugLogButton } from '../components/DebugLogPanel'
import ThemeModeToggle from '../components/ThemeModeToggle'
import WindowControls from '../components/WindowControls'
import { pushLog } from '../debugLog'
import { clearVpnLogs } from '../vpnLogStore'
import { authStrings as s } from '../authStrings'
import { needsNeonGlow, neonTextShadow, themeToUi, resolveThemeAssetUrl, type ClientTheme } from '../clientTheme'
import { useAppearanceMode } from '../appearanceStore'
import { isDebugBuild } from '../debugBuild'

type LoginStep = 'auth' | 'forgot'

export default function LoginScreen({
  theme,
  onLogin,
  initialReferralCode = '',
}: {
  theme: ClientTheme | null
  onLogin: (theme: ClientTheme | null) => void
  initialReferralCode?: string
}) {
  const [appearanceMode, toggleAppearance] = useAppearanceMode()
  const ui = useMemo(() => themeToUi(theme, appearanceMode), [theme, appearanceMode])
  const linkGlow = needsNeonGlow(ui.linkColor, ui.dark) ? neonTextShadow(ui.linkColor) : undefined

  const [step, setStep] = useState<LoginStep>('auth')
  const [tab, setTab] = useState<'login' | 'register'>(initialReferralCode ? 'register' : 'login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [referralOrPromo, setReferralOrPromo] = useState(initialReferralCode || '')
  const [showPassword, setShowPassword] = useState(false)
  const [rememberMe, setRememberMe] = useState(getRememberMe())
  const [forgotEmail, setForgotEmail] = useState('')
  const [forgotSent, setForgotSent] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [regDone, setRegDone] = useState(false)
  const [showDebugLog, setShowDebugLog] = useState(false)
  const [bootstrapStatus, setBootstrapStatus] = useState('')
  const [bootstrapReady, setBootstrapReady] = useState(false)

  const rememberLabel = theme?.login_remember_me_label || 'Запомнить меня'
  const forgotLabel = theme?.login_forgot_password_label || 'Забыли пароль?'
  const forgotTitle = theme?.login_forgot_title || 'Восстановление пароля'
  const forgotHint = theme?.login_forgot_instruction || 'Введите email — мы отправим ссылку.'
  const linkColor = ui.linkColor
  const refPromoLabel = theme?.register_referral_or_promo_label || 'Промокод или реферальный код'
  const refPromoHint = theme?.register_referral_or_promo_hint || 'Необязательно'

  const sessionExpired = isBootstrapExpired()

  useEffect(() => {
    if (initialReferralCode) {
      setReferralOrPromo(initialReferralCode)
      setTab('register')
    }
  }, [initialReferralCode])

  useEffect(() => {
    const savedEmail = getRememberedEmail()
    const savedPassword = getRememberedPassword()
    if (savedEmail) {
      setEmail(savedEmail)
      setRememberMe(true)
    }
    if (savedPassword) setPassword(savedPassword)
  }, [])

  useEffect(() => {
    const api_ = (window as any).electronAPI
    if (!api_) return
    const onVpnError = (msg: string) => {
      const text = String(msg || '').trim()
      if (!text) return
      pushLog('Login', text, 'E')
      setError(text)
    }
    api_.onVpnError?.(onVpnError)
  }, [])

  useEffect(() => {
    if (isLoggedIn()) {
      // Авторизованный пользователь не должен запускать bootstrap на старте.
      resetBootstrapRendererState()
      return
    }
    if (sessionExpired) {
      setBootstrapReady(false)
      return
    }
    let alive = true
    setBootstrapReady(false)
    setBootstrapStatus(s.connectingWait)
    setBootstrapStatusListener((msg) => {
      if (!alive) return
      // Не блокировать paint — статус через rAF
      requestAnimationFrame(() => {
        if (!alive) return
        setBootstrapStatus(msg)
        setBootstrapReady(/Канал готов|Осталось \d+:\d+/i.test(msg))
      })
    })
    // Дать UI отрисовать «Подключение…» до тяжёлого vpnConnect (WG install)
    const startTimer = window.setTimeout(() => {
      if (!alive) return
      void ensureBootstrapVpn().then((ok) => {
        if (!alive) return
        if (ok) {
          setBootstrapReady(true)
          return
        }
        setBootstrapReady(false)
        setBootstrapStatus(s.bootstrapFail)
      })
    }, 120)
    return () => {
      alive = false
      window.clearTimeout(startTimer)
      setBootstrapStatusListener(null)
    }
  }, [sessionExpired])

  const openLoginSession = async (): Promise<{ ok: boolean; subscriptionExpired?: boolean }> => {
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
      const status = Number((e as any).response?.status) || 0
      // Только жёсткий отказ сервера (лимит устройств) — сбрасываем сессию.
      // Таймаут/сеть после успешного login не должны выкидывать на пустой экран входа.
      if (status === 403 || status === 409) {
        clearTokens()
      }
      setError(formatApiError(e, status
        ? 'Достигнут лимит устройств (3). Выйдите на другом устройстве.'
        : 'Не удалось зарегистрировать устройство. Проверьте сеть и попробуйте снова.'))
      return { ok: false }
    }
  }

  const finishAuth = async () => {
    saveRememberMe(email, password, rememberMe)
    const sessionResult = await openLoginSession()
    if (!sessionResult.ok) {
      if (sessionResult.subscriptionExpired) {
        // Prefetch пока tunnel ещё жив, UI не ждём WG-uninstall
        await prefetchLoginDataViaBootstrap().catch(() => false)
        const themeRes = await api.get('/api/vpn/theme', { timeout: 15_000 }).catch(() => ({ data: theme }))
        onLogin(themeRes.data ?? theme)
        void disconnectBootstrapVpn().catch(() => null)
        resetBootstrapRendererState()
      }
      return
    }

    // 1) Пока bootstrap WG поднят — профиль/хеши/тема через main IPC (быстро).
    // 2) Сразу на главный экран — не ждём «Остановка службы wg-turn».
    // 3) Bootstrap гасим в фоне.
    clearVpnLogs()
    let themeData = theme
    try {
      await prefetchLoginDataViaBootstrap()
      const themeRes = await api.get('/api/vpn/theme', { timeout: 15_000 })
      if (themeRes.data) themeData = themeRes.data
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      pushLog('Login', `prefetch: ${msg}`, 'W')
    }
    onLogin(themeData)
    void disconnectBootstrapVpn()
      .catch(() => null)
      .finally(() => resetBootstrapRendererState())
  }

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      // Как Android: при bootstrap API через main → 10.66.66.1 (renderer xhr на public timeout).
      pushLog('Login', isBootstrapVpnActive() ? 'auth via bootstrap tunnel (main IPC)' : 'auth public HTTPS')
      const res = await api.post('/api/auth/login', { email, password }, { timeout: 25_000 })
      saveTokens(res.data.access_token, res.data.refresh_token)
      await finishAuth()
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
      const payload: { email: string; password: string; referral_or_promo?: string } = { email, password }
      const code = referralOrPromo.trim()
      if (code) payload.referral_or_promo = code
      await api.post('/api/auth/register', payload, { timeout: 25_000 })
      saveRememberMe(email, password, rememberMe)
      setRegDone(true)
    } catch (err: any) {
      setError(formatApiError(err, 'Ошибка регистрации'))
    } finally {
      setLoading(false)
    }
  }

  const handleForgot = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.post('/api/auth/forgot-password', { email: forgotEmail || email }, { timeout: 25_000 })
      setForgotSent(true)
    } catch (err: any) {
      setError(formatApiError(err, 'Ошибка отправки'))
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
    disabled: boolean,
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
        disabled={disabled}
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

  const statusBlock = () => {
    if (sessionExpired) return null
    const text = bootstrapStatus || s.channelReady
    const isReady = /Канал готов|Осталось \d+:\d+/i.test(text)
    return (
      <p className="mb-4 text-xs leading-relaxed" style={{ color: isReady ? ui.green : ui.hint }}>
        {text}
      </p>
    )
  }

  const handleCloseApp = () => {
    // Сразу quit — не ждать WG uninstall (иначе «Закрыть» кажется мёртвой).
    // before-quit в main всё равно сделает cleanupVpn.
    try {
      ;(window as any).electronAPI?.quitApp?.()
    } catch { /* ignore */ }
    void shutdownBootstrapBeforeExit().catch(() => null)
  }

  const authBlocked = sessionExpired || (!bootstrapReady && !/не удалось|ошибк|fail|WireGuard/i.test(bootstrapStatus))
  const authSubmitDisabled =
    loading || authBlocked || !email.trim() || !password.trim()

  return (
    <div
      className="flex flex-col h-full"
      style={{ background: ui.bg, color: ui.fg, fontFamily: ui.fontFamily }}
    >
      <div
        className="flex justify-end px-4 py-2.5"
        style={{ WebkitAppRegion: 'drag' } as React.CSSProperties}
      >
        <div
          className="flex items-center gap-1.5"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <ThemeModeToggle mode={appearanceMode} onToggle={toggleAppearance} color={ui.fg} />
          <DebugLogButton onClick={() => setShowDebugLog(true)} />
          <WindowControls />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-5 pt-6 pb-5">
        <div className="flex flex-col items-center w-full">
          <SilentLogo
            size={56}
            imageUrl={
              isDebugBuild
                ? resolveThemeAssetUrl(theme?.logo_url)
                : undefined
            }
          />
          <p className="mt-3 text-base font-bold tracking-[0.2em]" style={{ color: ui.fg }}>
            {ui.appTitle}
          </p>
        </div>

        {step === 'auth' && (
          <div className="mt-5">
            {statusBlock()}

            <div
              className="flex rounded-xl p-1 mb-4"
              style={{
                background: ui.tabBg,
                opacity: sessionExpired ? 0.4 : 1,
              }}
            >
              {(['login', 'register'] as const).map(key => (
                <button
                  key={key}
                  type="button"
                  disabled={sessionExpired}
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
                  {key === 'login' ? 'Войти' : 'Регистрация'}
                </button>
              ))}
            </div>

            {sessionExpired ? (
              <LoginExpiredPanel
                fg={ui.fg}
                hint={ui.hint}
                accentColor={ui.red}
                primaryBtnBg={ui.primaryBtnBg}
                primaryBtnFg={ui.primaryBtnFg}
                onCloseApp={handleCloseApp}
              />
            ) : regDone ? (
              <div className="text-center pt-8">
                <p className="font-medium text-sm" style={{ color: ui.fg }}>{s.confirmEmail}</p>
                <p className="text-xs mt-1" style={{ color: ui.hint }}>{s.emailSent(email)}</p>
                <p className="text-[11px] mt-0.5 text-center leading-relaxed" style={{ color: ui.hint }}>
                  Откройте ссылку из письма (браузер или почта) — временный VPN включён
                </p>
                <button
                  type="button"
                  onClick={() => { setTab('login'); setRegDone(false) }}
                  className="mt-4 text-xs hover:opacity-80"
                  style={{ color: ui.fg, background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  Войти
                </button>
              </div>
            ) : (
              <form onSubmit={tab === 'login' ? handleLogin : handleRegister}>
                <p className="text-xs mb-1" style={{ color: ui.label }}>Email</p>
                <input
                  className={fieldCls + ' mb-3'}
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
                <p className="text-xs mb-1" style={{ color: ui.label }}>Пароль</p>
                {passwordField(password, setPassword, showPassword, () => setShowPassword(v => !v), false)}
                {tab === 'register' && (
                  <>
                    <p className="text-xs mb-1" style={{ color: ui.label }}>{refPromoLabel}</p>
                    <input
                      className={fieldCls + ' mb-3'}
                      style={{
                        background: ui.fieldBg,
                        color: ui.fieldText,
                        border: `1px solid ${ui.border}`,
                      }}
                      type="text"
                      value={referralOrPromo}
                      onChange={e => setReferralOrPromo(e.target.value)}
                      placeholder={refPromoHint}
                      autoComplete="off"
                    />
                  </>
                )}
                <div className="flex items-center justify-between py-2 text-xs">
                  <label className="flex items-center gap-2 cursor-pointer" style={{ color: ui.hint }}>
                    <ThemeCheckbox
                      checked={rememberMe}
                      onChange={setRememberMe}
                      fg={ui.fg}
                      bg={ui.bg}
                      border={ui.border}
                    />
                    {rememberLabel}
                  </label>
                  {tab === 'login' && (
                    <button
                      type="button"
                      onClick={() => { setForgotEmail(email); setStep('forgot'); setError(''); setForgotSent(false) }}
                      className="hover:opacity-80 text-[11px]"
                      style={{
                        color: linkColor,
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        textShadow: linkGlow,
                      }}
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
                  disabled={authSubmitDisabled}
                  className="w-full h-12 rounded-xl text-sm font-semibold disabled:opacity-40"
                  style={{ background: ui.primaryBtnBg, color: ui.primaryBtnFg }}
                  title={
                    !bootstrapReady && !sessionExpired
                      ? 'Дождитесь готовности канала'
                      : undefined
                  }
                >
                  {loading
                    ? '…'
                    : !bootstrapReady && !sessionExpired
                      ? 'Ожидание канала…'
                      : tab === 'login'
                        ? 'Войти'
                        : 'Зарегистрироваться'}
                </button>
              </form>
            )}
          </div>
        )}

        {step === 'forgot' && (
          <div className="mt-5">
            {sessionExpired ? (
              <LoginExpiredPanel
                fg={ui.fg}
                hint={ui.hint}
                accentColor={ui.red}
                primaryBtnBg={ui.primaryBtnBg}
                primaryBtnFg={ui.primaryBtnFg}
                onCloseApp={handleCloseApp}
              />
            ) : (
              <>
            <p className="text-sm font-semibold" style={{ color: ui.fg }}>{forgotTitle}</p>
            <p className="text-xs mb-4 leading-relaxed" style={{ color: ui.hint }}>{forgotHint}</p>
            {forgotSent ? (
              <div className="text-xs text-center py-6 space-y-2">
                <p style={{ color: ui.green }}>
                  Если email зарегистрирован, письмо отправлено.
                </p>
                <p style={{ color: ui.hint }}>
                  Откройте ссылку из письма в браузере — смените пароль на странице сайта, затем войдите в приложение.
                </p>
              </div>
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
              onClick={() => { setStep('auth'); setError('') }}
              className="w-full mt-4 text-xs hover:opacity-80"
              style={{ color: ui.hint, background: 'none', border: 'none', cursor: 'pointer' }}
            >
              ← Назад к входу
            </button>
              </>
            )}
          </div>
        )}
      </div>
      <DebugLogPanel open={showDebugLog} onClose={() => setShowDebugLog(false)} />
    </div>
  )
}
