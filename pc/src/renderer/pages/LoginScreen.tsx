import { useState, useEffect, useMemo } from 'react'
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
  setBootstrapStatusListener,
} from '../bootstrapVpn'
import HashInputSection from '../components/HashInputSection'
import SilentLogo from '../components/SilentLogo'
import DebugLogPanel, { DebugLogButton } from '../components/DebugLogPanel'
import TitleBar from '../components/TitleBar'
import { pushLog } from '../debugLog'
import { authStrings as s } from '../authStrings'
import { themeToUi, type ClientTheme } from '../clientTheme'

export default function LoginScreen({
  theme,
  onLogin,
}: {
  theme: ClientTheme | null
  onLogin: (theme: ClientTheme | null) => void
}) {
  const ui = useMemo(() => themeToUi(theme), [theme])

  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [regDone, setRegDone] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const [bootstrapConnecting, setBootstrapConnecting] = useState(false)
  const [bootstrapReady, setBootstrapReady] = useState(isBootstrapVpnActive())
  const [bootstrapHash, setBootstrapHash] = useState<string | null>(getBootstrapHash)
  const [showDebugLog, setShowDebugLog] = useState(false)

  useEffect(() => {
    setBootstrapHash(getBootstrapHash())
    const active = isBootstrapVpnActive()
    setBootstrapReady(active)
    if (active) setStatusMsg(s.channelReady)
    setBootstrapStatusListener(msg => {
      setStatusMsg(msg)
      setBootstrapReady(isBootstrapVpnActive())
      if (msg.includes('истекло')) {
        setBootstrapHash(getBootstrapHash())
      }
    })
    return () => setBootstrapStatusListener(null)
  }, [])

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
      if (!ok || !active) {
        setStatusMsg(s.bootstrapFail)
        setBootstrapReady(false)
      }
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
        setError(s.needBootstrap)
        return
      }
      const res = await api.post('/api/auth/login', { email, password })
      saveTokens(res.data.access_token, res.data.refresh_token)
      if (!(await openLoginSession())) return
      await disconnectBootstrapVpn()
      setBootstrapReady(false)
      setStatusMsg(s.internetOff)
      const themeRes = await api.get('/api/vpn/theme').catch(() => ({ data: theme }))
      onLogin(themeRes.data ?? theme)
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
      if (!isBootstrapVpnActive()) {
        setError(s.needBootstrap)
        return
      }
      await api.post('/api/auth/register', { email, password })
      setRegDone(true)
    } catch (err: any) {
      setError(formatApiError(err, 'Ошибка регистрации'))
    } finally {
      setLoading(false)
    }
  }

  const fieldCls =
    'w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none transition-colors'

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
          <p
            className="mt-3 w-full text-center text-base font-bold tracking-[0.3em]"
            style={{ color: ui.fg }}
          >
            SILENT
          </p>
        </div>

        <HashInputSection
          bootstrapHash={bootstrapHash}
          statusMsg={statusMsg}
          bootstrapConnecting={bootstrapConnecting}
          bootstrapReady={bootstrapReady}
          onConnect={connectForLogin}
          ui={ui}
        />

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
            <p className="font-medium text-sm" style={{ color: ui.fg }}>
              {s.confirmEmail}
            </p>
            <p className="text-xs mt-1" style={{ color: ui.hint }}>
              {s.emailSent(email)}
            </p>
            <button
              type="button"
              onClick={() => {
                setTab('login')
                setRegDone(false)
              }}
              className="mt-4 text-xs hover:opacity-80"
              style={{ color: ui.fg }}
            >
              {s.login}
            </button>
          </div>
        ) : (
          <form onSubmit={tab === 'login' ? handleLogin : handleRegister}>
            <label className="text-xs" style={{ color: ui.label }}>
              {s.email}
            </label>
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
            <label className="text-xs" style={{ color: ui.label }}>
              {s.password}
            </label>
            <input
              className={fieldCls + ' mt-1 mb-3'}
              style={{
                background: ui.fieldBg,
                color: ui.fieldText,
                border: `1px solid ${ui.border}`,
              }}
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              required
            />
            {error && (
              <p className="text-xs mb-2" style={{ color: ui.red }}>
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={loading || !email.trim() || !password.trim()}
              className="w-full py-3 rounded-xl text-sm font-semibold disabled:opacity-40"
              style={{ background: ui.primaryBtnBg, color: ui.primaryBtnFg }}
            >
              {loading ? '…' : tab === 'login' ? s.login : s.registerSubmit}
            </button>
          </form>
        )}
      </div>
      <DebugLogPanel open={showDebugLog} onClose={() => setShowDebugLog(false)} />
    </div>
  )
}
