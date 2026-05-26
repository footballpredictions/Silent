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
}

type PreviewScreen = 'main' | 'menu' | 'subscription'

export default function ClientPreview({ theme, platform = 'mobile' }: {
  theme: ClientTheme
  platform?: 'mobile' | 'pc'
}) {
  const [screen, setScreen] = useState<PreviewScreen>('main')
  const [connected, setConnected] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)

  const w = 265
  const h = 606
  const scale = platform === 'pc' ? 0.72 : 0.72
  const appTitle = (theme.app_name || 'Silent').toUpperCase()
  const fg = theme.text_color
  const bg = theme.background_color
  const muted = `${fg}66`
  const green = '#16A34A'

  const statusText = connected ? 'Подключено' : 'Отключено'
  const statusColor = connected ? green : muted

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
        <button type="button" onClick={() => { setMenuOpen(true); setScreen('menu') }}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: fg, fontSize: 14, padding: 0 }}>☰</button>
        <div style={{ flex: 1, textAlign: 'center', fontWeight: 700, fontSize: 12, letterSpacing: 4 }}>{appTitle}</div>
        <div style={{ width: 16 }} />
      </div>

      {/* Main */}
      {screen === 'main' && (
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
            <div style={{ fontSize: 12, fontWeight: 600, color: green }}>Оплачено</div>
            <div style={{ fontSize: 12, color: muted, marginTop: 2 }}>до 26.06.2026</div>
          </div>
        </>
      )}

      {/* Menu drawer overlay */}
      {menuOpen && screen === 'menu' && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', zIndex: 10 }}>
          <div style={{ width: 208, background: bg, borderRight: '0.5px solid #E5E7EB', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: 16, borderBottom: '0.5px solid #F3F4F6', display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>user@mail.ru</div>
                <div style={{ fontSize: 11, color: muted, marginTop: 2 }}>Аккаунт: ABC123</div>
              </div>
              <button type="button" onClick={() => { setMenuOpen(false); setScreen('main') }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: fg }}>✕</button>
            </div>
            <div style={{ flex: 1, padding: 8 }}>
              {[
                ['subscription', 'Подписка'],
                ['settings', 'VK / офлайн'],
                ['promo', 'Промокод'],
                ['devices', 'Сессии (1/3)'],
                ['support', 'Поддержка'],
                ['about', 'О сервисе'],
              ].map(([key, label]) => (
                <button key={key} type="button" onClick={() => key === 'subscription' && setScreen('subscription')}
                  style={{
                    width: '100%', textAlign: 'left', padding: '10px 12px', fontSize: 14,
                    background: 'none', border: 'none', cursor: 'pointer', color: fg,
                    display: 'flex', justifyContent: 'space-between',
                  }}>
                  {label}<span style={{ color: muted }}>›</span>
                </button>
              ))}
              <button type="button" style={{
                width: '100%', textAlign: 'left', padding: '10px 12px', fontSize: 14,
                background: 'none', border: 'none', cursor: 'pointer', color: '#EF4444', marginTop: 8,
              }}>Выйти</button>
            </div>
          </div>
          <div style={{ flex: 1, background: 'rgba(0,0,0,0.2)' }}
            onClick={() => { setMenuOpen(false); setScreen('main') }} />
        </div>
      )}

      {screen === 'subscription' && (
        <div style={{ flex: 1, padding: 16, overflow: 'auto' }}>
          <button type="button" onClick={() => { setScreen('menu'); setMenuOpen(true) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: muted, fontSize: 12, marginBottom: 16 }}>← Назад</button>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>Выберите тариф</div>
          {[
            ['Месяц', '199 ₽'],
            ['3 месяца', '499 ₽'],
            ['Год', '1 499 ₽'],
          ].map(([label, price]) => (
            <div key={label} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              background: theme.primary_color, color: bg,
              borderRadius: 12, padding: '10px 12px', marginBottom: 8, fontSize: 12, fontWeight: 600,
            }}>
              <span>{label}</span><span>{price}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        {(['main', 'menu', 'subscription'] as PreviewScreen[]).map(s => (
          <button key={s} type="button" onClick={() => {
            setScreen(s)
            setMenuOpen(s === 'menu')
          }} style={{
            padding: '6px 12px', fontSize: 11, borderRadius: 8, cursor: 'pointer',
            background: screen === s ? '#fff' : '#222', color: screen === s ? '#000' : '#aaa',
            border: '1px solid #333',
          }}>
            {s === 'main' ? 'Главная' : s === 'menu' ? 'Меню' : 'Подписка'}
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
