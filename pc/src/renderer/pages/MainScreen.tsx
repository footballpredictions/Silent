import { useState, useEffect, useCallback } from 'react'
import { Menu, X, ChevronRight, Pencil } from 'lucide-react'
import api, {
  clearTokens,
  getDeviceFingerprint,
  getSessionDeviceId,
  saveSessionDeviceId,
  clearSessionFingerprint,
  clearSessionDeviceId,
} from '../api'
import {
  cacheVpnConfig, fetchConfigFromVk, getCachedVpnConfig, clearCachedVpnConfig,
  getVkAccessToken, getVkUserId, saveVkUserId, getBootstrapHash,
  type VpnConfigPayload,
} from '../vkConfig'
import { disconnectBootstrapVpn, fetchBootstrapConfig, isBootstrapVpnActive } from '../bootstrapVpn'
import { waitVpnReady } from '../vpnReady'
import DebugLogPanel, { DebugLogButton } from '../components/DebugLogPanel'
import { resolveAppName } from '../clientTheme'
import { MENU_DRAWER_CLASS, UI_COLORS } from '../uiTokens'
import AppExclusionsPanel from '../components/AppExclusionsPanel'
import MenuHashesPanel from '../components/MenuHashesPanel'
import { applyWorkerCount } from '../hashChannelHelper'
import { pushLog } from '../debugLog'

interface DeviceInfo {
  id: string
  device_name: string
  device_type: string
  is_connected: boolean
  last_connected?: string | null
}

interface Profile {
  email: string; display_id: string
  is_admin?: boolean
  vk_linked?: boolean; vk_user_id?: number | null
  subscription: { is_active: boolean; plan_type: string | null; expires_at: string | null; days_left: number }
  devices: DeviceInfo[]
  devices_count: number
  max_devices: number
}

type MenuPage = null | 'devices' | 'subscription' | 'exceptions' | 'hashes' | 'promo' | 'support' | 'about'

const GREEN = '#16A34A'

function deviceTypeLabel(type: string): string {
  const t = (type || '').toLowerCase()
  if (t === 'android') return 'Android'
  if (t === 'pc' || t === 'windows') return 'ПК'
  if (t === 'ios') return 'iOS'
  return type ? type.charAt(0).toUpperCase() + type.slice(1) : '—'
}

function defaultDeviceName(type: string): string {
  const t = (type || '').toLowerCase()
  if (t === 'android') return 'Android'
  if (t === 'pc' || t === 'windows') return 'PC'
  if (t === 'ios') return 'iOS'
  return deviceTypeLabel(type)
}

function sessionCustomLabel(d: DeviceInfo): string | null {
  const defaults = new Set(['Android', 'ПК', 'PC', 'iOS', 'Windows'])
  if (defaults.has(d.device_name) || d.device_name.startsWith('Bootstrap-')) return null
  return d.device_name
}

export default function MainScreen({ theme: initialTheme, onLogout }: { theme: any; onLogout: () => void }) {
  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [clientTheme, setClientTheme] = useState<any>(initialTheme)
  const sessionDeviceId = getSessionDeviceId()
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPage, setMenuPage] = useState<MenuPage>(null)
  const [promoCode, setPromoCode] = useState('')
  const [promoMsg, setPromoMsg] = useState('')
  const [showDebugLog, setShowDebugLog] = useState(false)
  const [renameTarget, setRenameTarget] = useState<DeviceInfo | null>(null)
  const [renameText, setRenameText] = useState('')
  const [renameSaving, setRenameSaving] = useState(false)
  const [activeWorkers, setActiveWorkers] = useState(0)

  const fetchProfile = useCallback(async () => {
    try {
      const res = await api.get('/api/users/me')
      setProfile(res.data)
      if (res.data.vk_user_id) saveVkUserId(res.data.vk_user_id)
      return res.data as Profile
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    fetchProfile()
    const subMsg = localStorage.getItem('silent_subscription_msg')
    if (subMsg) {
      localStorage.removeItem('silent_subscription_msg')
      setMenuOpen(true)
      setMenuPage('subscription')
    }
  }, [fetchProfile])

  useEffect(() => {
    if (menuPage !== 'devices') return
    fetchProfile()
    const id = window.setInterval(() => fetchProfile(), 5000)
    return () => clearInterval(id)
  }, [menuPage, fetchProfile])

  useEffect(() => {
    api.get('/api/vpn/theme').then(r => setClientTheme(r.data)).catch(() => {})
  }, [])

  const markOnlineOnServer = useCallback(async () => {
    const fp = getDeviceFingerprint()
    try {
      await api.post('/api/vpn/connect', { device_fingerprint: fp, device_type: 'pc' })
      await fetchProfile()
    } catch {
      /* ignore */
    }
  }, [fetchProfile])

  useEffect(() => {
    const api_ = (window as any).electronAPI
    if (!api_?.onVpnStopped) return
    const onStopped = () => {
      setConnected(false)
      setConnecting(false)
      setActiveWorkers(0)
    }
    const onError = (msg: string) => {
      pushLog('VPN', msg, 'E')
      setConnecting(false)
      setConnected(false)
    }
    const onReady = (ok: boolean) => {
      if (ok) {
        setConnected(true)
        setConnecting(false)
        void markOnlineOnServer()
      }
    }
    const onLog = (line: string) => {
      if (!line?.trim()) return
      const m = line.match(/Активных:\s*(\d+)/)
      if (m) setActiveWorkers(parseInt(m[1], 10))
      const level = /error|ошиб|fail|таймаут/i.test(line) ? 'E' : 'I'
      pushLog('VPN', line.trim(), level)
    }
    api_.onVpnStopped(onStopped)
    api_.onVpnError?.(onError)
    api_.onVpnReady?.(onReady)
    api_.onVpnLog?.(onLog)
    return () => api_.removeVpnListeners?.()
  }, [markOnlineOnServer])

  useEffect(() => {
    if (!connected) return
    const id = window.setInterval(() => fetchProfile(), 10000)
    return () => clearInterval(id)
  }, [connected, fetchProfile])

  const DEVICE_FINGERPRINT = () => getDeviceFingerprint()

  const handleToggle = async () => {
    if (connecting) return
    setConnecting(true)
    pushLog('Main', connected ? 'disconnect' : 'connect start')
    try {
      const fp = DEVICE_FINGERPRINT()
      if (!connected) {
        if (isBootstrapVpnActive()) {
          await disconnectBootstrapVpn()
          pushLog('Main', 'bootstrap VPN stopped before connect')
          await new Promise(r => setTimeout(r, 500))
        }
        const p = await fetchProfile()
        const hasAccess = !p || p.is_admin || p.subscription?.is_active
        if (!hasAccess) {
          alert('Пробный период закончился. Оформите подписку в меню → Подписка.')
          setMenuOpen(true)
          setMenuPage('subscription')
          return
        }

        let config: VpnConfigPayload | null = null
        try {
          const reg = await api.post('/api/vpn/device/register', {
            device_name: 'PC',
            device_type: 'pc',
            device_fingerprint: fp,
          })
          config = reg.data
          cacheVpnConfig(config!)
          if (config.device_id) saveSessionDeviceId(String(config.device_id))
          pushLog('Main', `device/register OK device=${String(config.device_id || '').slice(0, 8)} hashes=${config.vk_hashes?.length ?? 0}`)
        } catch (e: any) {
          if (e.response?.status === 402) {
            alert(e.response?.data?.detail || 'Оформите подписку для доступа к интернету.')
            setMenuOpen(true)
            setMenuPage('subscription')
            fetchProfile()
            return
          }
          pushLog('Main', `device/register fail: ${e.response?.data?.detail || e.message}`, 'W')
          try {
            const cfg = await api.get(`/api/vpn/config?fingerprint=${fp}`)
            config = cfg.data
            cacheVpnConfig(config!)
          } catch {
            const boot = getBootstrapHash()
            if (boot) {
              const bootCfg = await fetchBootstrapConfig()
              if (bootCfg) {
                config = bootCfg
                cacheVpnConfig(config)
              }
            }
          }
        }
        if (!config) {
          const vkId = profile?.vk_user_id || getVkUserId()
          if (vkId) config = await fetchConfigFromVk(vkId, getVkAccessToken())
          if (config) cacheVpnConfig(config)
        }
        if (!config) config = getCachedVpnConfig()
        if (!config) {
          pushLog('Main', 'no VPN config', 'E')
          alert('Сервер недоступен. Выйдите и настройте hash на экране входа.')
          return
        }
        if (!config.wg_private_key?.trim() || !config.server_public_key?.trim()) {
          pushLog('Main', 'missing WG keys', 'E')
          alert('Нет ключей WireGuard. Перезайдите в аккаунт или проверьте сервер.')
          return
        }
        if ((window as any).electronAPI?.vpnConnect) {
          pushLog('Main', 'vpnConnect start')
          const connectCfg = applyWorkerCount(config)
          pushLog('Main', `vpnConnect n=${connectCfg.stream_count} hashes=${connectCfg.vk_hashes?.length ?? 0}`)
          const res = await (window as any).electronAPI.vpnConnect(connectCfg)
          if (res?.error) { pushLog('Main', `vpnConnect: ${res.error}`, 'E'); alert(res.error); return }
          const ready = await waitVpnReady(90000)
          if (!ready) {
            pushLog('Main', 'connect timeout', 'E')
            alert('WireGuard не поднялся')
            await (window as any).electronAPI?.vpnDisconnect?.()
            return
          }
          await markOnlineOnServer()
        }
        setConnected(true)
      } else {
        if ((window as any).electronAPI?.vpnDisconnect) {
          await (window as any).electronAPI.vpnDisconnect()
        }
        await api.post('/api/vpn/disconnect', { device_fingerprint: fp }).catch(() => null)
        setConnected(false)
      }
      fetchProfile()
    } catch (err: any) {
      if (err.response?.status === 402 || err.response?.status === 403) alert(err.response.data.detail)
    } finally { setConnecting(false) }
  }

  const handleLogout = async () => {
    const fp = (() => { try { return DEVICE_FINGERPRINT() } catch { return null } })()
    if (connected || connecting) {
      await (window as any).electronAPI?.vpnDisconnect?.()
      if (fp) await api.post('/api/vpn/disconnect', { device_fingerprint: fp }).catch(() => null)
    }
    if (fp) {
      await api.post('/api/users/logout', { device_fingerprint: fp }).catch(() => null)
    }
    clearCachedVpnConfig()
    clearSessionDeviceId()
    clearSessionFingerprint()
    clearTokens()
    onLogout()
  }

  const saveRename = async () => {
    if (!renameTarget || renameSaving) return
    setRenameSaving(true)
    try {
      const name = renameText.trim() || defaultDeviceName(renameTarget.device_type)
      await api.patch(`/api/users/devices/${renameTarget.id}`, { device_name: name })
      setRenameTarget(null)
      fetchProfile()
    } catch (e: any) {
      alert(e.response?.data?.detail || 'Ошибка переименования')
    } finally {
      setRenameSaving(false)
    }
  }

  const bg = clientTheme?.background_color || '#ffffff'
  const fg = clientTheme?.text_color || '#000000'
  const toggleOn = clientTheme?.toggle_on_color || '#000000'
  const toggleOff = clientTheme?.toggle_off_color || '#cccccc'
  const fontFamily = clientTheme?.font_family ? `${clientTheme.font_family}, Inter, sans-serif` : 'Inter, sans-serif'
  const appTitle = resolveAppName(clientTheme?.app_name).toUpperCase()
  const muted = `${fg}66`

  const statusLabel = connecting ? 'Подключение...' : connected ? 'Подключено' : 'Отключено'
  const statusColor = connecting ? `${fg}99` : connected ? GREEN : muted
  const localOnline = connected || connecting

  return (
    <div className="relative flex flex-col h-full overflow-hidden" style={{ background: bg, color: fg, fontFamily }}>
      <div
        className="h-9 flex-shrink-0 relative flex items-center border-b border-gray-100 px-2"
        style={{ WebkitAppRegion: 'drag', background: bg } as React.CSSProperties}
      >
        <button
          onClick={() => { setMenuOpen(true); setMenuPage(null) }}
          style={{ WebkitAppRegion: 'no-drag', color: fg } as React.CSSProperties}
          className="p-1 hover:opacity-60 transition-opacity z-10"
        >
          <Menu className="w-4 h-4" />
        </button>
        <span
          className="absolute left-1/2 -translate-x-1/2 text-xs font-bold tracking-widest truncate max-w-[120px] pointer-events-none"
          style={{ color: fg }}
        >
          {appTitle}
        </span>
        <div
          className="ml-auto flex items-center gap-1 z-10"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <DebugLogButton onClick={() => setShowDebugLog(true)} />
          <button
            onClick={() => (window as any).electronAPI?.minimize()}
            className="w-2.5 h-2.5 rounded-full bg-gray-300 hover:bg-gray-400 transition-colors"
          />
          <button
            onClick={() => (window as any).electronAPI?.close()}
            className="w-2.5 h-2.5 rounded-full bg-gray-300 hover:bg-red-400 transition-colors"
          />
        </div>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center pb-16 gap-6 px-4">
        <div className="text-center">
          <div className="text-xs font-medium tracking-widest uppercase" style={{ color: statusColor, letterSpacing: '0.15em' }}>
            {statusLabel}
          </div>
        </div>

        <button onClick={handleToggle} disabled={connecting}
          className="relative flex items-center transition-all active:scale-95"
          style={{ width: 120, height: 60 }}>
          <div className="toggle-track absolute inset-0 rounded-full"
            style={{ background: connected ? toggleOn : toggleOff }} />
          {connected && (
            <div className="pulse-ring absolute inset-0 rounded-full opacity-20"
              style={{ background: toggleOn }} />
          )}
          <div className="toggle-thumb absolute w-12 h-12 rounded-full shadow-lg"
            style={{
              background: bg,
              border: `2px solid ${connected ? toggleOn : toggleOff}`,
              transform: `translateX(${connected ? '64px' : '4px'})`,
              top: '4px',
            }} />
        </button>

        {connecting && (
          <div className="w-4 h-4 border-2 rounded-full animate-spin"
            style={{ borderColor: `${fg}33`, borderTopColor: fg }} />
        )}
      </div>

      <div className="absolute bottom-0 left-0 right-0 p-4 border-t" style={{ background: bg, borderColor: '#F3F4F6' }}>
        {profile?.is_admin || profile?.subscription?.plan_type === 'unlimited' ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: GREEN }}>Бессрочно</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>Полный доступ</div>
          </div>
        ) : profile?.subscription?.is_active && profile.subscription.plan_type === 'trial' ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: '#2563EB' }}>Пробный период</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>
              осталось {profile.subscription.days_left} дн.
            </div>
          </div>
        ) : profile?.subscription?.is_active ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: GREEN }}>Оплачено</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>
              до {profile.subscription.expires_at
                ? profile.subscription.expires_at.split('T')[0].split('-').reverse().join('.')
                : '—'}
            </div>
          </div>
        ) : (
          <button onClick={() => { setMenuOpen(true); setMenuPage('subscription') }}
            className="w-full rounded-xl py-2 text-xs font-semibold transition-colors"
            style={{ background: fg, color: bg }}>
            Оформить подписку
          </button>
        )}
      </div>

      {renameTarget && (
        <div className="absolute inset-0 z-[60] flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-xs rounded-xl p-4 shadow-xl" style={{ background: bg }}>
            <div className="text-sm font-semibold mb-3">Приписать имя</div>
            <input
              value={renameText}
              onChange={e => setRenameText(e.target.value.slice(0, 64))}
              placeholder="Например: Рабочий ПК"
              className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm mb-3 focus:outline-none focus:border-black"
              style={{ userSelect: 'text' } as any}
              autoFocus
            />
            <div className="flex gap-2">
              <button
                onClick={() => setRenameTarget(null)}
                disabled={renameSaving}
                className="flex-1 py-2 text-xs rounded-xl border border-gray-200"
              >
                Отмена
              </button>
              <button
                onClick={saveRename}
                disabled={renameSaving}
                className="flex-1 py-2 text-xs rounded-xl text-white bg-black disabled:opacity-50"
              >
                Сохранить
              </button>
            </div>
          </div>
        </div>
      )}

      {menuOpen && menuPage === null && (
        <div className="absolute inset-0 z-50 flex">
          <div
            className={`${MENU_DRAWER_CLASS} h-full flex flex-col`}
            style={{ background: bg, borderRight: `1px solid ${UI_COLORS.gray200}` }}
          >
            <div
              className="p-4 flex items-center justify-between"
              style={{ borderBottom: `1px solid ${UI_COLORS.gray100}` }}
            >
              <div>
                <div className="text-xs font-semibold truncate max-w-[140px]">{profile?.email || '—'}</div>
                <div className="text-xs text-gray-400 mt-0.5">Аккаунт: {profile?.display_id || '—'}</div>
                {sessionDeviceId && (
                  <div className="text-xs text-gray-400 mt-0.5">
                    Сессия: {sessionDeviceId.slice(0, 8).toUpperCase()}
                  </div>
                )}
              </div>
              <button
                onClick={() => { setMenuOpen(false); setMenuPage(null) }}
                className="p-1 hover:opacity-60"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <nav className="flex-1 p-2 overflow-y-auto">
              {[
                { key: 'subscription', label: 'Подписка' },
                { key: 'exceptions', label: 'Исключения приложений' },
                { key: 'hashes', label: 'Хеши' },
                { key: 'promo', label: 'Промокод' },
                { key: 'devices', label: `Сессии (${profile?.devices_count || 0}/${profile?.max_devices || 3})` },
                { key: 'support', label: 'Поддержка' },
                { key: 'about', label: 'О сервисе' },
              ].map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setMenuPage(key as MenuPage)}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm text-left transition-colors"
                  style={{ color: fg }}
                >
                  <span className="flex-1 text-left leading-snug">{label}</span>
                  <ChevronRight className="w-3.5 h-3.5 shrink-0" style={{ color: muted }} />
                </button>
              ))}
              <button onClick={handleLogout}
                className="w-full text-left px-3 py-2.5 rounded-lg text-sm text-red-500 hover:bg-red-50 transition-colors mt-2">
                Выйти
              </button>
            </nav>
          </div>
          <div className="flex-1 bg-black/20" onClick={() => { setMenuOpen(false); setMenuPage(null) }} />
        </div>
      )}

      {menuOpen && menuPage !== null && (
        <div
          className="absolute inset-0 z-50 flex flex-col h-full w-full overflow-hidden"
          style={{ background: bg }}
        >
          {menuPage === 'subscription' && (
            <div className="flex-1 p-4 overflow-y-auto w-full">
              <button
                type="button"
                onClick={() => setMenuPage(null)}
                className="text-xs text-gray-400 mb-4 flex items-center gap-1"
              >
                ← Назад
              </button>
              {profile?.subscription?.is_active ? (
                <div className="space-y-2">
                  <div className="text-sm font-semibold">Подписка активна</div>
                  <div className="text-xs text-gray-500">
                    Тариф: {{
                      trial: 'Пробный период',
                      monthly: 'Месяц',
                      quarterly: '3 месяца',
                      yearly: 'Год',
                    }[profile.subscription?.plan_type || ''] || profile.subscription?.plan_type}<br />
                    Осталось: {profile.subscription?.days_left ?? 0} дней
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="text-sm font-semibold">Выберите тариф</div>
                  {[
                    { id: 'monthly', label: 'Месяц', price: '199 ₽' },
                    { id: 'quarterly', label: '3 месяца', price: '499 ₽' },
                    { id: 'yearly', label: 'Год', price: '1 499 ₽' },
                  ].map(plan => (
                    <button key={plan.id}
                      onClick={async () => {
                        try {
                          const res = await api.post('/api/payments/init', { plan_type: plan.id })
                          ;(window as any).electronAPI?.openExternal(res.data.url)
                        } catch (e: any) {
                          alert(e.response?.data?.detail || 'Ошибка')
                        }
                      }}
                      className="w-full flex items-center justify-between bg-black text-white rounded-xl px-3 py-2.5 text-xs font-semibold hover:bg-gray-800 transition-colors">
                      <span>{plan.label}</span>
                      <span>{plan.price}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {menuPage === 'exceptions' && (
            <div className="flex-1 flex flex-col min-h-0 w-full h-full items-stretch text-left">
              <AppExclusionsPanel fg={fg} muted={muted} onBack={() => setMenuPage(null)} />
            </div>
          )}

          {menuPage === 'hashes' && (
            <MenuHashesPanel
              fg={fg}
              muted={muted}
              vpnConnected={connected}
              activeWorkers={activeWorkers}
              onBack={() => setMenuPage(null)}
            />
          )}

          {menuPage === 'promo' && (
            <div className="flex-1 p-4 w-full overflow-y-auto">
              <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
              <div className="text-sm font-semibold mb-3">Промокод</div>
              <input value={promoCode} onChange={e => setPromoCode(e.target.value)}
                placeholder="Введите код"
                className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-black"
                style={{ userSelect: 'text' } as any} />
              <button onClick={async () => {
                try {
                  const res = await api.post('/api/payments/promo/check', { code: promoCode, plan_type: 'monthly' })
                  setPromoMsg(`Скидка ${res.data.discount_percent}%!`)
                } catch (e: any) { setPromoMsg(e.response?.data?.detail || 'Не найден') }
              }} className="mt-2 w-full bg-black text-white rounded-xl py-2 text-xs font-semibold hover:bg-gray-800 transition-colors">
                Применить
              </button>
              {promoMsg && <p className="text-xs text-gray-500 mt-2 text-center">{promoMsg}</p>}
            </div>
          )}

          {menuPage === 'devices' && (
            <div className="flex-1 p-4 overflow-y-auto text-left w-full">
              <button type="button" onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4 block text-left">
                ← Назад
              </button>
              <div className="text-sm font-semibold mb-1 text-left">Сессии</div>
              <div className="text-[11px] mb-3 text-left" style={{ color: muted }}>
                VPN онлайн: {profile?.devices?.filter(d => d.is_connected || (localOnline && d.id === sessionDeviceId)).length || 0} из {profile?.devices_count || 0}
              </div>
              {!profile?.devices?.length && (
                <p className="text-xs text-left" style={{ color: muted }}>Нет зарегистрированных устройств</p>
              )}
              {profile?.devices?.map(d => {
                const isSelf = sessionDeviceId != null && String(d.id) === String(sessionDeviceId)
                const online = d.is_connected || (localOnline && isSelf)
                return (
                  <div key={d.id} className="flex items-center gap-2 py-2.5 border-b border-gray-100 text-left">
                    <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${online ? 'bg-green-500' : 'bg-gray-300'}`} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate" style={{ color: fg }}>
                        {deviceTypeLabel(d.device_type)}
                        {isSelf && (
                          <span className="font-normal text-[11px]" style={{ color: muted }}> · это вы</span>
                        )}
                      </div>
                      {sessionCustomLabel(d) && (
                        <div className="text-[11px] truncate mt-0.5" style={{ color: muted }}>
                          {sessionCustomLabel(d)}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => {
                        setRenameTarget(d)
                        setRenameText(sessionCustomLabel(d) || '')
                      }}
                      className="p-1.5 rounded-lg hover:bg-gray-100 shrink-0"
                      title="Подписать"
                    >
                      <Pencil className="w-3.5 h-3.5" style={{ color: muted }} />
                    </button>
                  </div>
                )
              })}
            </div>
          )}

          {menuPage === 'support' && (
            <div className="flex-1 p-4 w-full overflow-y-auto">
              <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
              <div className="text-sm font-semibold mb-3">Поддержка</div>
              <p className="text-xs text-gray-500">По вопросам обратитесь через email или Telegram.</p>
            </div>
          )}

          {menuPage === 'about' && (
            <div className="flex-1 p-4 w-full overflow-y-auto">
              <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
              <div className="text-sm font-semibold mb-1">Silent VPN</div>
              <div className="text-xs text-gray-500 space-y-1">
                <p>Версия 1.0.32</p>
                <p>WireGuard-туннель через VK TURN/DTLS</p>
              </div>
            </div>
          )}
        </div>
      )}
      <DebugLogPanel open={showDebugLog} onClose={() => setShowDebugLog(false)} />
    </div>
  )
}
