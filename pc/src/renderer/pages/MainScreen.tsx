import { useState, useEffect, useCallback } from 'react'
import { Menu, X, ChevronRight } from 'lucide-react'
import api, { clearTokens } from '../api'

interface Profile {
  email: string; display_id: string; is_admin: boolean
  subscription: { is_active: boolean; plan_type: string | null; expires_at: string | null; days_left: number }
  devices: any[]; devices_count: number; max_devices: number
}

const DEVICE_FINGERPRINT = (() => {
  let fp = localStorage.getItem('device_fp')
  if (!fp) { fp = Math.random().toString(36).slice(2) + Date.now().toString(36); localStorage.setItem('device_fp', fp) }
  return fp
})()

export default function MainScreen({ theme, onLogout }: { theme: any; onLogout: () => void }) {
  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPage, setMenuPage] = useState<null | 'devices' | 'subscription' | 'settings' | 'promo' | 'support' | 'about'>( null)
  const [promoCode, setPromoCode] = useState('')
  const [promoMsg, setPromoMsg] = useState('')

  const fetchProfile = useCallback(async () => {
    try {
      const res = await api.get('/api/users/me')
      setProfile(res.data)
    } catch {}
  }, [])

  useEffect(() => { fetchProfile() }, [])

  const handleToggle = async () => {
    if (connecting) return
    setConnecting(true)
    try {
      if (!connected) {
        // Register device & connect
        await api.post('/api/vpn/device/register', {
          device_name: 'PC',
          device_type: 'pc',
          device_fingerprint: DEVICE_FINGERPRINT,
        }).catch(() => null)
        await api.post('/api/vpn/connect', {
          device_fingerprint: DEVICE_FINGERPRINT,
          device_type: 'pc',
        })
        setConnected(true)
      } else {
        await api.post('/api/vpn/disconnect', { device_fingerprint: DEVICE_FINGERPRINT })
        setConnected(false)
      }
      fetchProfile()
    } catch (err: any) {
      if (err.response?.status === 402) alert('Нет активной подписки')
      else if (err.response?.status === 403) alert(err.response.data.detail)
    } finally { setConnecting(false) }
  }

  const handleLogout = async () => {
    if (connected) {
      await api.post('/api/vpn/disconnect', { device_fingerprint: DEVICE_FINGERPRINT }).catch(() => null)
    }
    clearTokens()
    onLogout()
  }

  const bg = theme?.background_color || '#ffffff'
  const fg = theme?.text_color || '#000000'
  const toggleOn = theme?.toggle_on_color || '#000000'
  const toggleOff = theme?.toggle_off_color || '#cccccc'

  return (
    <div className="relative flex flex-col h-full overflow-hidden" style={{ background: bg, color: fg }}>
      {/* Title bar - draggable */}
      <div className="h-9 flex items-center px-3 flex-shrink-0 border-b border-gray-100"
        style={{ WebkitAppRegion: 'drag', background: bg } as any}>
        <button onClick={() => setMenuOpen(true)}
          style={{ WebkitAppRegion: 'no-drag', color: fg } as any}
          className="p-1 hover:opacity-60 transition-opacity">
          <Menu className="w-4 h-4" />
        </button>
        <span className="text-xs font-bold tracking-widest mx-auto">SILENT</span>
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
          <div className={`text-xs font-medium tracking-widest uppercase ${connected ? 'text-green-600' : 'text-gray-400'}`}>
            {connecting ? 'Подключение...' : connected ? 'Подключено' : 'Отключено'}
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
          <div className="w-4 h-4 border-2 border-gray-300 border-t-black rounded-full animate-spin" />
        )}
      </div>

      {/* Bottom subscription info */}
      <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-gray-100" style={{ background: bg }}>
        {profile?.is_admin || profile?.subscription.plan_type === 'unlimited' ? (
          <div className="text-center">
            <div className="text-xs font-semibold text-green-600">Бессрочно</div>
            <div className="text-xs text-gray-400 mt-0.5">Полный доступ</div>
          </div>
        ) : profile?.subscription.is_active ? (
          <div className="text-center">
            <div className="text-xs font-semibold text-green-600">Оплачено</div>
            <div className="text-xs text-gray-400 mt-0.5">
              до {profile.subscription.expires_at?.split('T')[0].split('-').reverse().join('.')}
            </div>
          </div>
        ) : (
          <button onClick={() => { setMenuOpen(true); setMenuPage('subscription') }}
            className="w-full bg-black text-white rounded-xl py-2 text-xs font-semibold hover:bg-gray-800 transition-colors">
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
              </div>
              <button onClick={() => { setMenuOpen(false); setMenuPage(null) }}
                className="p-1 hover:opacity-60"><X className="w-4 h-4" /></button>
            </div>

            {menuPage === null && (
              <nav className="flex-1 p-2 overflow-y-auto">
                {[
                  { key: 'subscription', label: 'Подписка' },
                  { key: 'settings', label: 'Настройки' },
                  { key: 'promo', label: 'Промокод' },
                  { key: 'devices', label: `Устройства (${profile?.devices_count || 0}/${profile?.max_devices || 3})` },
                  { key: 'support', label: 'Поддержка' },
                  { key: 'about', label: 'О сервисе' },
                ].map(({ key, label }) => (
                  <button key={key} onClick={() => setMenuPage(key as any)}
                    className="w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm hover:bg-gray-100 transition-colors">
                    {label}
                    <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
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
                <div className="text-sm font-semibold mb-3">Устройства</div>
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
              <div className="flex-1 p-4">
                <button onClick={() => setMenuPage(null)} className="text-xs text-gray-400 mb-4">← Назад</button>
                <div className="text-sm font-semibold mb-3">Настройки</div>
                <p className="text-xs text-gray-500">Исключения приложений доступны на мобильных клиентах.</p>
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
