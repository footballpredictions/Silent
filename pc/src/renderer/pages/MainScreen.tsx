import { useState, useEffect, useCallback } from 'react'
import { Menu, X, ChevronRight } from 'lucide-react'
import api, {
  clearTokens,
  getDeviceFingerprint,
  getSessionDeviceId,
  clearSessionFingerprint,
  clearSessionDeviceId,
} from '../api'
import {
  cacheVpnConfig, fetchConfigFromVk, getCachedVpnConfig, clearCachedVpnConfig,
  getVkAccessToken, getVkUserId, saveVkUserId,
  type VpnConfigPayload,
} from '../vkConfig'

interface Profile {
  email: string; display_id: string
  is_admin?: boolean
  vk_linked?: boolean; vk_user_id?: number | null
  subscription: { is_active: boolean; plan_type: string | null; expires_at: string | null; days_left: number }
  devices: any[]; devices_count: number; max_devices: number
}

const GREEN = '#16A34A'

export default function MainScreen({ theme: initialTheme, onLogout }: { theme: any; onLogout: () => void }) {
  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [clientTheme, setClientTheme] = useState<any>(initialTheme)
  const sessionDeviceId = getSessionDeviceId()
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPage, setMenuPage] = useState<null | 'devices' | 'subscription' | 'settings' | 'promo' | 'support' | 'about'>( null)
  const [promoCode, setPromoCode] = useState('')
  const [promoMsg, setPromoMsg] = useState('')

  const fetchProfile = useCallback(async () => {
    try {
      const res = await api.get('/api/users/me')
      setProfile(res.data)
      if (res.data.vk_user_id) saveVkUserId(res.data.vk_user_id)
    } catch {}
  }, [])

  useEffect(() => { fetchProfile() }, [])

  useEffect(() => {
    api.get('/api/vpn/theme').then(r => setClientTheme(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    const api_ = (window as any).electronAPI
    if (!api_?.onVpnStopped) return
    const onStopped = () => {
      setConnected(false)
      setConnecting(false)
    }
    const onError = (msg: string) => {
      alert(msg)
      setConnecting(false)
      setConnected(false)
    }
    api_.onVpnStopped(onStopped)
    api_.onVpnError?.(onError)
    return () => api_.removeVpnListeners?.()
  }, [])

  const DEVICE_FINGERPRINT = () => getDeviceFingerprint()

  const waitVpnReady = (timeoutMs = 90000): Promise<boolean> =>
    new Promise(resolve => {
      const api_ = (window as any).electronAPI
      if (!api_?.onVpnReady) { resolve(true); return }
      let done = false
      const finish = (ok: boolean) => {
        if (done) return
        done = true
        clearTimeout(timer)
        resolve(ok)
      }
      const handler = (ok: boolean) => finish(!!ok)
      api_.onVpnReady(handler)
      const timer = setTimeout(() => finish(false), timeoutMs)
    })

  const handleToggle = async () => {
    if (connecting) return
    setConnecting(true)
    try {
      const fp = DEVICE_FINGERPRINT()
      if (!connected) {
        let config: VpnConfigPayload | null = null
        try {
          const reg = await api.post('/api/vpn/device/register', {
            device_name: 'PC',
            device_type: 'pc',
            device_fingerprint: fp,
          })
          config = reg.data
          cacheVpnConfig(config!)
        } catch (e: any) {
          if (e.response?.status === 402) { alert('Нет активной подписки'); return }
          try {
            const cfg = await api.get(`/api/vpn/config?fingerprint=${fp}`)
            config = cfg.data
            cacheVpnConfig(config!)
          } catch {}
        }
        if (!config) {
          const vkId = profile?.vk_user_id || getVkUserId()
          if (vkId) config = await fetchConfigFromVk(vkId, getVkAccessToken())
          if (config) cacheVpnConfig(config)
        }
        if (!config) config = getCachedVpnConfig()
        if (!config) {
          alert('Сервер недоступен. Выйдите и настройте VK на экране входа.')
          return
        }
        if (!config.wg_private_key?.trim() || !config.server_public_key?.trim()) {
          alert('Нет ключей WireGuard. Перезайдите в аккаунт или проверьте сервер.')
          return
        }
        try {
          await api.post('/api/vpn/connect', { device_fingerprint: fp, device_type: 'pc' })
        } catch {}
        if ((window as any).electronAPI?.vpnConnect) {
          const res = await (window as any).electronAPI.vpnConnect(config)
          if (res?.error) { alert(res.error); return }
          const ready = await waitVpnReady()
          if (!ready) {
            alert('Таймаут подключения WireGuard')
            await (window as any).electronAPI?.vpnDisconnect?.()
            return
          }
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
      if (err.response?.status === 403) alert(err.response.data.detail)
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

  const bg = clientTheme?.background_color || '#ffffff'
  const fg = clientTheme?.text_color || '#000000'
  const toggleOn = clientTheme?.toggle_on_color || '#000000'
  const toggleOff = clientTheme?.toggle_off_color || '#cccccc'
  const fontFamily = clientTheme?.font_family ? `${clientTheme.font_family}, Inter, sans-serif` : 'Inter, sans-serif'
  const appTitle = (clientTheme?.app_name || 'Silent').toUpperCase()
  const muted = `${fg}66`

  const statusLabel = connecting ? 'Подключение...' : connected ? 'Подключено' : 'Отключено'
  const statusColor = connecting ? `${fg}99` : connected ? GREEN : muted

  return (
    <div className="relative flex flex-col h-full overflow-hidden" style={{ background: bg, color: fg, fontFamily }}>
      {/* Title bar - draggable */}
      <div className="h-9 flex items-center px-3 flex-shrink-0 border-b border-gray-100"
        style={{ WebkitAppRegion: 'drag', background: bg } as any}>
        <button onClick={() => setMenuOpen(true)}
          style={{ WebkitAppRegion: 'no-drag', color: fg } as any}
          className="p-1 hover:opacity-60 transition-opacity">
          <Menu className="w-4 h-4" />
        </button>
        <span className="text-xs font-bold tracking-widest mx-auto">{appTitle}</span>
        <div className="flex gap-1.5" style={{ WebkitAppRegion: 'no-drag' } as any}>
          <button onClick={() => (window as any).electronAPI?.minimize()}
            className="w-2.5 h-2.5 rounded-full bg-gray-300 hover:bg-gray-400 transition-colors" />
          <button onClick={() => (window as any).electronAPI?.close()}
            className="w-2.5 h-2.5 rounded-full bg-gray-300 hover:bg-red-400 transition-colors" />
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col items-center justify-center pb-16 gap-6 px-4">
        {/* Status */}
        <div className="text-center">
          <div className="text-xs font-medium tracking-widest uppercase" style={{ color: statusColor, letterSpacing: '0.15em' }}>
            {statusLabel}
          </div>
        </div>

        {/* Big Toggle */}
        <button onClick={handleToggle} disabled={connecting}
          className="relative flex items-center transition-all active:scale-95"
          style={{ width: 120, height: 60 }}>
          <div className="toggle-track absolute inset-0 rounded-full"
            style={{ background: connected ? toggleOn : toggleOff }} />
          {/* Pulse ring when connected */}
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

        {/* Connecting spinner */}
        {connecting && (
          <div className="w-4 h-4 border-2 rounded-full animate-spin"
            style={{ borderColor: `${fg}33`, borderTopColor: fg }} />
        )}
      </div>

      {/* Bottom subscription info */}
      <div className="absolute bottom-0 left-0 right-0 p-4 border-t" style={{ background: bg, borderColor: '#F3F4F6' }}>
        {profile?.is_admin || profile?.subscription?.plan_type === 'unlimited' ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: GREEN }}>Бессрочно</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>Полный доступ</div>
          </div>
        ) : profile?.subscription?.is_active ? (
          <div className="text-center">
            <div className="text-xs font-semibold" style={{ color: GREEN }}>Оплачено</div>
            <div className="text-xs mt-0.5" style={{ color: muted }}>
              до {profile.subscription.expires_at?.split('T')[0].split('-').reverse().join('.')}
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

      {/* Side Drawer Menu */}
      {menuOpen && (
        <div className="absolute inset-0 z-50 flex">
          <div className="slide-in w-52 h-full shadow-2xl flex flex-col"
            style={{ background: bg, borderRight: '1px solid #e5e7eb' }}>
            {/* Drawer header */}
            <div className="p-4 border-b border-gray-100 flex items-center justify-between">
              <div>
                <div className="text-xs font-semibold truncate max-w-[140px]">{profile?.email || '—'}</div>
                <div className="text-xs text-gray-400 mt-0.5">ID: {profile?.display_id || '—'}</div>
                {sessionDeviceId && (
                  <div className="text-xs text-gray-400 mt-0.5">
                    Сессия: {sessionDeviceId.slice(0, 8).toUpperCase()}
                  </div>
                )}
              </div>
              <button onClick={() => { setMenuOpen(false); setMenuPage(null) }}
                className="p-1 hover:opacity-60"><X className="w-4 h-4" /></button>
            </div>

            {menuPage === null && (
              <nav className="flex-1 p-2 overflow-y-auto">
                {[
                  { key: 'subscription', label: 'Подписка' },
                  { key: 'settings', label: 'VK / офлайн' },
                  { key: 'promo', label: 'Промокод' },
                  { key: 'devices', label: `Сессии (${profile?.devices_count || 0}/${profile?.max_devices || 3})` },
                  { key: 'support', label: 'Поддержка' },
                  { key: 'about', label: 'О сервисе' },
                ].map(({ key, label }) => (
                  <button key={key} onClick={() => setMenuPage(key as any)}
                    className="w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-colors"
                    style={{ color: fg }}>
                    {label}
                    <ChevronRight className="w-3.5 h-3.5" style={{ color: muted }} />
                  </button>
                ))}
                <button onClick={handleLogout}
                  className="w-full text-left px-3 py-2.5 rounded-lg text-sm text-red-500 hover:bg-red-50 transition-colors mt-2">
                  Выйти
                </button>
              </nav>
            )}

            {menuPage === 'subscription' && (
              <div className="flex-1 p-4 overflow-y-auto">
                <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4 flex items-center gap-1">
                  ← Назад
                </button>
                {profile?.subscription.is_active ? (
                  <div className="space-y-2">
                    <div className="text-sm font-semibold">Подписка активна</div>
                    <div className="text-xs text-gray-500">
                      Тариф: {profile.subscription.plan_type}<br />
                      Осталось: {profile.subscription.days_left} дней
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

            {menuPage === 'promo' && (
              <div className="flex-1 p-4">
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
              <div className="flex-1 p-4 overflow-y-auto">
                <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
                <div className="text-xs font-semibold mb-3">Сессии</div>
                {profile?.devices.map(d => (
                  <div key={d.id} className="flex items-center gap-2 py-2 border-b border-gray-100">
                    <div className={`w-1.5 h-1.5 rounded-full ${d.is_connected ? 'bg-green-500' : 'bg-gray-300'}`} />
                    <div>
                      <div className="text-xs font-medium">{d.device_name}</div>
                      <div className="text-xs text-gray-400">{d.device_type}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {menuPage === 'support' && (
              <div className="flex-1 p-4">
                <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
                <div className="text-sm font-semibold mb-3">Поддержка</div>
                <p className="text-xs text-gray-500">По вопросам обратитесь через email или Telegram.</p>
              </div>
            )}

            {menuPage === 'about' && (
              <div className="flex-1 p-4">
                <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
                <div className="text-sm font-semibold mb-1">Silent VPN</div>
                <div className="text-xs text-gray-500 space-y-1">
                  <p>Версия 1.0.0</p>
                  <p>WireGuard-туннель через VK TURN/DTLS</p>
                </div>
              </div>
            )}

            {menuPage === 'settings' && (
              <div className="flex-1 p-4 overflow-y-auto">
                <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
                <div className="text-sm font-semibold mb-3">VK</div>
                <p className="text-xs text-gray-500">
                  {profile?.vk_linked || profile?.vk_user_id
                    ? `VK привязан (ID ${profile.vk_user_id}). Настройка — на экране входа.`
                    : 'VK не привязан. Выйдите и настройте VK на экране входа.'}
                </p>
              </div>
            )}
          </div>

          {/* Overlay */}
          <div className="flex-1 bg-black/20" onClick={() => { setMenuOpen(false); setMenuPage(null) }} />
        </div>
      )}
    </div>
  )
}
