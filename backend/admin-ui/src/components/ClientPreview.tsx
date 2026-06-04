import { useState } from 'react'

export type ClientTheme = {
  primary_color: string
  background_color: string
  text_color: string
  accent_color: string
  toggle_on_color: string
  toggle_off_color: string
  font_family: string
  app_name: string
  update_bar_background_color?: string
  update_bar_text_color?: string
  update_bar_progress_color?: string
  update_bar_label_available?: string
  update_bar_label_downloading?: string
}

type PreviewScreen =
  | 'main'
  | 'main_update'
  | 'main_download'
  | 'menu'
  | 'subscription'
  | 'exceptions'
  | 'hashes'
  | 'promo'
  | 'devices'
  | 'support'
  | 'about'

const SCREEN_TABS: { id: PreviewScreen; label: string }[] = [
  { id: 'main', label: 'Главная' },
  { id: 'main_update', label: 'Обновление' },
  { id: 'main_download', label: 'Загрузка' },
  { id: 'menu', label: 'Меню' },
  { id: 'subscription', label: 'Подписка' },
  { id: 'exceptions', label: 'Исключения' },
  { id: 'hashes', label: 'Хеши' },
  { id: 'promo', label: 'Промокод' },
  { id: 'devices', label: 'Сессии' },
  { id: 'support', label: 'Поддержка' },
  { id: 'about', label: 'О сервисе' },
]

const MENU_ITEMS: { id: PreviewScreen; label: string; badge?: string }[] = [
  { id: 'subscription', label: 'Подписка', badge: 'Активна' },
  { id: 'exceptions', label: 'Исключения приложений' },
  { id: 'hashes', label: 'Хеши' },
  { id: 'promo', label: 'Промокод' },
  { id: 'devices', label: 'Сессии', badge: '1/3' },
  { id: 'support', label: 'Поддержка' },
  { id: 'about', label: 'О сервисе' },
]

export default function ClientPreview({ theme, platform = 'mobile' }: {
  theme: ClientTheme
  platform?: 'mobile' | 'pc'
}) {
  const [screen, setScreen] = useState<PreviewScreen>('main')
  const [connected, setConnected] = useState(true)

  const w = 265
  const h = 606
  const scale = platform === 'pc' ? 0.72 : 0.72
  const appTitle = (theme.app_name || 'Silent VPN').toUpperCase()
  const fg = theme.text_color
  const bg = theme.background_color
  const muted = `${fg}66`
  const green = '#16A34A'
  const updateBg = theme.update_bar_background_color || '#2563EB'
  const updateFg = theme.update_bar_text_color || '#FFFFFF'
  const updateProgress = theme.update_bar_progress_color || '#1D4ED8'
  const updateLabel = theme.update_bar_label_available || 'Доступно обновление'
  const downloadLabel = theme.update_bar_label_downloading || 'Скачивание…'
  const showMain = screen === 'main' || screen === 'main_update' || screen === 'main_download'
  const showUpdateBar = screen === 'main_update' || screen === 'main_download'
  const updateDownloading = screen === 'main_download'
  const updateProgressPct = 47

  const statusText = connected ? 'Подключено' : 'Отключено'
  const statusColor = connected ? green : muted

  const goTo = (s: PreviewScreen) => setScreen(s)

  const backBtn = (target: PreviewScreen = 'menu') => (
    <button type="button" onClick={() => goTo(target)}
      style={{ background: 'none', border: 'none', cursor: 'pointer', color: muted, fontSize: 12, marginBottom: 16, padding: 0 }}>
      ← Назад
    </button>
  )

  const subPage = (title: string, children: React.ReactNode) => (
    <div style={{ flex: 1, padding: 16, overflow: 'auto' }}>
      {backBtn('menu')}
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>{title}</div>
      {children}
    </div>
  )

  const menuDrawer = () => (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', zIndex: 10 }}>
      <div style={{
        width: 208, background: bg, borderRight: '0.5px solid #E5E7EB',
        display: 'flex', flexDirection: 'column',
      }}>
        <div style={{
          padding: 16, borderBottom: '0.5px solid #F3F4F6',
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
        }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600 }}>user@mail.ru</div>
            <div style={{ fontSize: 11, color: muted, marginTop: 2 }}>Аккаунт: ABC123</div>
            <div style={{ fontSize: 10, color: `${fg}59`, marginTop: 2 }}>Сессия: A1B2C3D4</div>
          </div>
          <button type="button" onClick={() => goTo('main')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: fg, fontSize: 14, padding: 0 }}>✕</button>
        </div>
        <div style={{ flex: 1, padding: '4px 0', overflow: 'auto' }}>
          {MENU_ITEMS.map(item => (
            <button key={item.id} type="button" onClick={() => goTo(item.id)}
              style={{
                width: '100%', textAlign: 'left', padding: '10px 12px', fontSize: 13,
                background: 'none', border: 'none', cursor: 'pointer', color: fg,
                display: 'flex', alignItems: 'center', gap: 6,
                borderBottom: `0.5px solid ${fg}0F`,
              }}>
              <span style={{ flex: 1 }}>{item.label}</span>
              {item.badge && (
                <span style={{ fontSize: 11, color: muted }}>{item.badge}</span>
              )}
              <span style={{ color: `${fg}4D`, fontSize: 12 }}>›</span>
            </button>
          ))}
          <button type="button" style={{
            width: '100%', textAlign: 'left', padding: '10px 12px', fontSize: 13,
            background: 'none', border: 'none', cursor: 'pointer', color: '#EF4444', marginTop: 4,
          }}>Выйти</button>
        </div>
      </div>
      <div style={{ flex: 1, background: 'rgba(0,0,0,0.2)' }} onClick={() => goTo('main')} />
    </div>
  )

  const shell = (
    <div style={{
      width: w, height: h, background: bg, color: fg,
      fontFamily: theme.font_family || 'Inter, sans-serif',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      borderRadius: platform === 'mobile' ? 20 : 8,
      border: `1px solid ${theme.accent_color}33`,
      boxShadow: '0 8px 32px rgba(0,0,0,0.35)',
      position: 'relative',
    }}>
      {/* Title bar */}
      <div style={{
        height: 36, display: 'flex', alignItems: 'center', padding: '0 12px',
        borderBottom: '0.5px solid #F3F4F6',
      }}>
        <button type="button" onClick={() => goTo('menu')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: fg, fontSize: 14, padding: 0 }}>☰</button>
        <div style={{ flex: 1, textAlign: 'center', fontWeight: 700, fontSize: 12, letterSpacing: 4 }}>{appTitle}</div>
        <div style={{ width: 16 }} />
      </div>

      {showMain && (
        <>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 24 }}>
            <div style={{ fontSize: 12, fontWeight: 500, letterSpacing: 2, color: statusColor, textTransform: 'uppercase' }}>
              {statusText}
            </div>
            <button type="button" onClick={() => setConnected(c => !c)} style={{
              width: 120, height: 60, borderRadius: 30, border: 'none', cursor: 'pointer',
              background: connected ? theme.toggle_on_color : theme.toggle_off_color,
              position: 'relative', padding: 0,
            }}>
              <div style={{
                position: 'absolute', top: 4,
                left: connected ? 64 : 4,
                width: 48, height: 48, borderRadius: '50%',
                background: bg,
                border: `2px solid ${connected ? theme.toggle_on_color : theme.toggle_off_color}`,
                transition: 'left 0.3s',
              }} />
            </button>
          </div>
          <div style={{ borderTop: '0.5px solid #F3F4F6', padding: 16, textAlign: 'center' }}>
            {showUpdateBar ? (
              <button type="button" style={{
                width: '100%', borderRadius: 12, border: 'none', cursor: 'default',
                background: updateBg, color: updateFg, padding: '10px 12px',
                fontSize: 12, fontWeight: 600, position: 'relative', overflow: 'hidden',
              }}>
                {updateDownloading && (
                  <div style={{
                    position: 'absolute', left: 0, top: 0, bottom: 0,
                    width: `${updateProgressPct}%`, background: updateProgress, opacity: 0.35,
                  }} />
                )}
                <span style={{ position: 'relative' }}>
                  {updateDownloading
                    ? `${downloadLabel} ${updateProgressPct}%`
                    : `${updateLabel} v1.0.73`}
                </span>
              </button>
            ) : (
              <>
                <div style={{ fontSize: 12, fontWeight: 600, color: green }}>Оплачено</div>
                <div style={{ fontSize: 12, color: muted, marginTop: 2 }}>до 26.06.2026</div>
              </>
            )}
          </div>
        </>
      )}

      {screen === 'menu' && menuDrawer()}

      {screen === 'subscription' && subPage('Выберите тариф', (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[
            ['Месяц', '199 ₽'],
            ['3 месяца', '499 ₽'],
            ['Год', '1 499 ₽'],
          ].map(([label, price]) => (
            <div key={label} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              background: theme.primary_color, color: bg,
              borderRadius: 12, padding: '10px 12px', fontSize: 12, fontWeight: 600,
            }}>
              <span>{label}</span><span>{price}</span>
            </div>
          ))}
        </div>
      ))}

      {screen === 'exceptions' && subPage('Исключения приложений', (
        <>
          <div style={{ fontSize: 11, color: muted, marginBottom: 10 }}>
            Приложения, которые не идут через VPN
          </div>
          <input readOnly value="Поиск приложений…" style={{
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 12,
            borderRadius: 10, border: `1px solid ${fg}22`, background: `${fg}08`, color: muted,
          }} />
          {['Telegram', 'YouTube', 'Chrome'].map(name => (
            <div key={name} style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '8px 0', borderBottom: `0.5px solid ${fg}12`, fontSize: 12,
            }}>
              <span>{name}</span>
              <div style={{ width: 18, height: 18, borderRadius: 4, border: `1.5px solid ${fg}44` }} />
            </div>
          ))}
        </>
      ))}

      {screen === 'hashes' && subPage('Хеши', (
        <>
          <div style={{ fontSize: 11, color: muted, marginBottom: 10 }}>Bootstrap и серверные хеши VK</div>
          {[
            ['Bootstrap', 'a1b2c3d4…', green],
            ['Сервер #0', 'e5f6g7h8…', green],
            ['Сервер #1', 'i9j0k1l2…', muted],
          ].map(([label, hash, dotColor]) => (
            <div key={label} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 0', borderBottom: `0.5px solid ${fg}12`, fontSize: 11,
            }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor as string }} />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 12 }}>{label}</div>
                <div style={{ fontFamily: 'monospace', color: muted, marginTop: 2 }}>{hash}</div>
              </div>
            </div>
          ))}
        </>
      ))}

      {screen === 'promo' && subPage('Промокод', (
        <>
          <input readOnly value="" placeholder="Введите код" style={{
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 12,
            borderRadius: 10, border: `1px solid ${fg}22`, background: bg, color: fg,
          }} />
          <button type="button" style={{
            marginTop: 8, width: '100%', padding: '8px 0', borderRadius: 10, border: 'none',
            background: theme.primary_color, color: bg, fontSize: 12, fontWeight: 600, cursor: 'default',
          }}>Применить</button>
        </>
      ))}

      {screen === 'devices' && subPage('Сессии', (
        <>
          <div style={{ fontSize: 11, color: muted, marginBottom: 10 }}>VPN онлайн: 1 из 1</div>
          {[
            ['Pixel 8', 'android', true],
            ['Windows PC', 'desktop', false],
          ].map(([name, type, online]) => (
            <div key={name as string} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 0', borderBottom: `0.5px solid ${fg}12`,
            }}>
              <div style={{
                width: 6, height: 6, borderRadius: '50%',
                background: online ? green : `${fg}33`,
              }} />
              <div>
                <div style={{ fontSize: 12, fontWeight: 500 }}>{name as string}</div>
                <div style={{ fontSize: 10, color: muted }}>{type as string}</div>
              </div>
            </div>
          ))}
        </>
      ))}

      {screen === 'support' && subPage('Поддержка', (
        <p style={{ fontSize: 12, color: muted, lineHeight: 1.5, margin: 0 }}>
          По вопросам обратитесь через email или Telegram.
        </p>
      ))}

      {screen === 'about' && subPage('Silent VPN', (
        <div style={{ fontSize: 12, color: muted, lineHeight: 1.6 }}>
          <p style={{ margin: '0 0 6px' }}>Версия 1.0.18</p>
          <p style={{ margin: 0 }}>WireGuard-туннель через VK TURN/DTLS</p>
        </div>
      ))}
    </div>
  )

  return (
    <div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {SCREEN_TABS.map(({ id, label }) => (
          <button key={id} type="button" onClick={() => goTo(id)} style={{
            padding: '5px 10px', fontSize: 10, borderRadius: 8, cursor: 'pointer',
            background: screen === id ? '#fff' : '#222', color: screen === id ? '#000' : '#aaa',
            border: '1px solid #333',
          }}>
            {label}
          </button>
        ))}
      </div>
      <div style={{ transform: `scale(${scale})`, transformOrigin: 'top center', height: h * scale }}>
        {shell}
      </div>
      <p style={{ textAlign: 'center', fontSize: 11, color: '#666', marginTop: 8 }}>
        Единый UI для Android, iOS и PC · {w}×{h}px
      </p>
    </div>
  )
}
