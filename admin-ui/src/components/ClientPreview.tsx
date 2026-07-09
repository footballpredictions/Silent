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
  dark_primary_color?: string
  dark_background_color?: string
  dark_text_color?: string
  dark_accent_color?: string
  dark_toggle_on_color?: string
  dark_toggle_off_color?: string
  dark_update_bar_background_color?: string
  dark_update_bar_text_color?: string
  dark_update_bar_progress_color?: string
  dark_login_link_color?: string
  login_remember_me_label?: string
  login_forgot_password_label?: string
  login_forgot_title?: string
  login_forgot_instruction?: string
  login_reset_title?: string
  login_reset_button_text?: string
  login_link_color?: string
  support_url?: string
  telegram_channel_url?: string
  privacy_url?: string
  terms_url?: string
  logo_url?: string
  menu_bonuses_label?: string
  bonuses_title?: string
  bonuses_intro_text?: string
  bonuses_referral_title?: string
  bonuses_referral_hint?: string
  bonuses_promo_title?: string
  bonuses_promo_hint?: string
  bonuses_rules_text?: string
  bonuses_copy_link_label?: string
  bonuses_copy_code_label?: string
  register_referral_or_promo_label?: string
  register_referral_or_promo_hint?: string
}

type PreviewScreen =
  | 'login'
  | 'login_forgot'
  | 'login_expired'
  | 'login_reset_web'
  | 'main'
  | 'main_update'
  | 'main_download'
  | 'menu'
  | 'subscription'
  | 'exceptions'
  | 'bonuses'
  | 'devices'
  | 'support'
  | 'about'

export type { PreviewScreen }

export const SCREEN_TABS: { id: PreviewScreen; label: string }[] = [
  { id: 'login', label: 'Вход' },
  { id: 'login_forgot', label: 'Восстановление' },
  { id: 'login_expired', label: 'Время вышло' },
  { id: 'login_reset_web', label: 'Сброс (web)' },
  { id: 'main', label: 'Главная' },
  { id: 'main_update', label: 'Обновление' },
  { id: 'main_download', label: 'Загрузка' },
  { id: 'menu', label: 'Меню' },
  { id: 'subscription', label: 'Подписка' },
  { id: 'exceptions', label: 'Исключения' },
  { id: 'bonuses', label: 'Бонусы' },
  { id: 'devices', label: 'Сессии' },
  { id: 'support', label: 'Поддержка' },
  { id: 'about', label: 'О сервисе' },
]

const MENU_ITEMS: { id: PreviewScreen; label: string; badge?: string }[] = [
  { id: 'subscription', label: 'Подписка', badge: 'Активна' },
  { id: 'exceptions', label: 'Исключения приложений' },
  { id: 'bonuses', label: 'Бонусы' },
  { id: 'devices', label: 'Сессии', badge: '1/3' },
  { id: 'support', label: 'Поддержка' },
  { id: 'about', label: 'О сервисе' },
]

const LOGIN_EXPIRED_TITLE = 'Время вышло'
const LOGIN_EXPIRED_BODY =
  'Время временного интернета истекло (2 мин). Закройте приложение и запустите снова.'
const LOGIN_EXPIRED_BTN = 'Закрыть приложение'

export default function ClientPreview({
  theme,
  platform = 'mobile',
  screen: controlledScreen,
  onScreenChange,
  hideTabs = false,
}: {
  theme: ClientTheme
  platform?: 'mobile' | 'pc'
  screen?: PreviewScreen
  onScreenChange?: (s: PreviewScreen) => void
  hideTabs?: boolean
}) {
  const [internalScreen, setInternalScreen] = useState<PreviewScreen>('main')
  const screen = controlledScreen ?? internalScreen
  const setScreen = (s: PreviewScreen) => {
    if (onScreenChange) onScreenChange(s)
    else setInternalScreen(s)
  }
  const [connected, setConnected] = useState(true)

  const w = 265
  const h = 606
  const scale = platform === 'pc' ? 0.72 : 0.72
  const fg = theme.text_color
  const bg = theme.background_color
  const muted = `${fg}66`
  const green = '#16A34A'
  const red = '#EF4444'
  const updateBg = theme.update_bar_background_color || '#2563EB'
  const updateFg = theme.update_bar_text_color || '#FFFFFF'
  const updateProgress = theme.update_bar_progress_color || '#1D4ED8'
  const updateLabel = theme.update_bar_label_available || 'Доступно обновление'
  const downloadLabel = theme.update_bar_label_downloading || 'Скачивание…'
  const showMain = screen === 'main' || screen === 'main_update' || screen === 'main_download'
  const showUpdateBar = screen === 'main_update' || screen === 'main_download'
  const updateDownloading = screen === 'main_download'
  const updateProgressPct = 47
  const linkColor = theme.login_link_color || '#4680C2'
  const isLoginPreview =
    screen === 'login' || screen === 'login_forgot' || screen === 'login_expired'

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

  const loginLogo = () => (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 20 }}>
      <div style={{
        width: 48, height: 48, borderRadius: '50%',
        background: `${fg}12`, marginBottom: 10,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 10, fontWeight: 700, color: fg, letterSpacing: 1,
      }}>SV</div>
      <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 3 }}>SILENT VPN</div>
    </div>
  )

  const themeCheckbox = (checked = false) => (
    <span style={{
      width: 14, height: 14, borderRadius: 3, flexShrink: 0,
      border: `1.5px solid ${checked ? fg : `${fg}55`}`,
      background: checked ? fg : bg,
      display: 'inline-block',
    }} />
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
        <div style={{ flex: 1, padding: '4px 8px', overflow: 'auto' }}>
          {MENU_ITEMS.map(item => (
            <button key={item.id} type="button" onClick={() => goTo(item.id)}
              style={{
                width: '100%', textAlign: 'left', padding: '10px 12px', fontSize: 13,
                background: 'none', border: 'none', cursor: 'pointer', color: fg,
                display: 'flex', alignItems: 'center', gap: 6,
                borderRadius: 8,
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
      {!isLoginPreview && screen !== 'login_reset_web' && (
        <div style={{
          height: 36, display: 'flex', alignItems: 'center', padding: '0 12px',
          borderBottom: '0.5px solid #F3F4F6',
        }}>
          <button type="button" onClick={() => goTo('menu')}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: fg, fontSize: 14, padding: 0 }}>☰</button>
          <div style={{ flex: 1, textAlign: 'center', fontWeight: 700, fontSize: 12, letterSpacing: 4 }}>SILENT VPN</div>
          <div style={{ width: 16 }} />
        </div>
      )}

      {screen === 'login' && (
        <div style={{ flex: 1, padding: '24px 16px 16px', overflow: 'auto' }}>
          {loginLogo()}
          <p style={{ fontSize: 11, fontWeight: 500, color: green, marginBottom: 12 }}>VPN включён</p>
          <div style={{ display: 'flex', borderRadius: 10, background: `${fg}0A`, padding: 3, marginBottom: 12 }}>
            <div style={{ flex: 1, textAlign: 'center', padding: '6px 0', fontSize: 10, fontWeight: 600, background: theme.primary_color, color: bg, borderRadius: 8 }}>Войти</div>
            <div style={{ flex: 1, textAlign: 'center', padding: '6px 0', fontSize: 10, color: muted }}>Регистрация</div>
          </div>
          <div style={{ fontSize: 10, color: muted, marginBottom: 4 }}>Email</div>
          <input readOnly placeholder="you@example.com" style={{
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 11, marginBottom: 10,
            borderRadius: 10, border: `1px solid ${fg}22`, background: `${fg}08`, color: fg,
          }} />
          <div style={{ fontSize: 10, color: muted, marginBottom: 4 }}>Пароль</div>
          <input readOnly type="password" placeholder="••••••••" style={{
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 11, marginBottom: 8,
            borderRadius: 10, border: `1px solid ${fg}22`, background: `${fg}08`, color: fg,
          }} />
          <div style={{ fontSize: 10, color: muted, marginBottom: 4 }}>
            {theme.register_referral_or_promo_label || 'Промокод или реферальный код'}
          </div>
          <input readOnly placeholder={theme.register_referral_or_promo_hint || 'Необязательно'} style={{
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 11, marginBottom: 8,
            borderRadius: 10, border: `1px solid ${fg}22`, background: `${fg}08`, color: fg,
          }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, fontSize: 10 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 5, color: muted }}>
              {themeCheckbox(true)}
              {theme.login_remember_me_label || 'Запомнить меня'}
            </label>
            <span style={{ color: linkColor, fontSize: 10 }}>{theme.login_forgot_password_label || 'Забыли пароль?'}</span>
          </div>
          <button type="button" style={{
            width: '100%', padding: '10px 0', borderRadius: 10, border: 'none',
            background: theme.primary_color, color: bg, fontSize: 11, fontWeight: 600,
          }}>Войти</button>
        </div>
      )}

      {screen === 'login_forgot' && (
        <div style={{ flex: 1, padding: '24px 16px 16px', overflow: 'auto' }}>
          {loginLogo()}
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>{theme.login_forgot_title || 'Восстановление пароля'}</div>
          <div style={{ fontSize: 10, color: muted, lineHeight: 1.5, marginBottom: 12 }}>
            {theme.login_forgot_instruction || 'Введите email — мы отправим ссылку.'}
          </div>
          <div style={{ fontSize: 10, color: muted, marginBottom: 4 }}>Email</div>
          <input readOnly placeholder="you@example.com" style={{
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 11, marginBottom: 10,
            borderRadius: 10, border: `1px solid ${fg}22`, background: `${fg}08`, color: fg,
          }} />
          <button type="button" style={{
            width: '100%', padding: '10px 0', borderRadius: 10, border: 'none',
            background: theme.primary_color, color: bg, fontSize: 11, fontWeight: 600,
          }}>Отправить письмо</button>
          <button type="button" style={{
            width: '100%', marginTop: 12, background: 'none', border: 'none', color: muted, fontSize: 10, cursor: 'pointer',
          }}>← Назад к входу</button>
        </div>
      )}

      {screen === 'login_expired' && (
        <div style={{ flex: 1, padding: '24px 16px 16px', overflow: 'auto' }}>
          {loginLogo()}
          <div style={{
            borderRadius: 14, padding: '18px 16px', textAlign: 'center',
            border: `1px solid ${red}2E`, background: `${red}0D`,
          }}>
            <div style={{
              width: 36, height: 36, borderRadius: '50%', margin: '0 auto 10px',
              background: `${red}1A`, display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 16,
            }}>⏱</div>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>{LOGIN_EXPIRED_TITLE}</div>
            <div style={{ fontSize: 10, color: muted, lineHeight: 1.5, marginBottom: 14 }}>{LOGIN_EXPIRED_BODY}</div>
            <button type="button" style={{
              width: '100%', padding: '10px 0', borderRadius: 10, border: 'none',
              background: fg, color: bg, fontSize: 11, fontWeight: 600,
            }}>{LOGIN_EXPIRED_BTN}</button>
          </div>
          <p style={{ fontSize: 9, color: `${fg}55`, textAlign: 'center', marginTop: 10, lineHeight: 1.4 }}>
            Тексты панели «Время вышло» зашиты в приложениях (bootstrap 2 мин)
          </p>
        </div>
      )}

      {screen === 'login_reset_web' && (
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: 16, background: '#0a0a0a',
        }}>
          <div style={{
            width: '100%', background: '#111', border: '1px solid #222',
            borderRadius: 14, padding: '24px 20px', textAlign: 'center',
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: 3, color: '#fff', opacity: 0.5, marginBottom: 16 }}>SILENT VPN</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', marginBottom: 8 }}>
              {theme.login_reset_title || 'Новый пароль'}
            </div>
            <p style={{ fontSize: 11, color: '#888', marginBottom: 14 }}>Аккаунт: <strong style={{ color: '#ccc' }}>user@mail.ru</strong></p>
            <input readOnly type="password" placeholder="••••••••" style={{
              width: '100%', boxSizing: 'border-box', padding: '10px 12px', fontSize: 11, marginBottom: 10,
              borderRadius: 10, border: '1px solid #333', background: '#1a1a1a', color: '#fff',
            }} />
            <button type="button" style={{
              width: '100%', padding: '11px 0', borderRadius: 10, border: 'none',
              background: '#fff', color: '#000', fontSize: 11, fontWeight: 700,
            }}>{theme.login_reset_button_text || 'Сохранить пароль'}</button>
            <p style={{ fontSize: 10, color: '#555', marginTop: 14, lineHeight: 1.5 }}>
              Страница из письма «Забыли пароль?» — открывается в браузере
            </p>
          </div>
        </div>
      )}

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
                    : `${updateLabel} v1.0.144`}
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

      {screen === 'bonuses' && subPage(theme.bonuses_title || theme.menu_bonuses_label || 'Бонусы', (
        <>
          <div style={{ fontSize: 10, color: muted, lineHeight: 1.5, marginBottom: 12, whiteSpace: 'pre-line' }}>
            {theme.bonuses_intro_text
              || theme.bonuses_rules_text
              || 'Рефералка: друг по ссылке/коду оплачивает подписку — оба +30 дней (до 10 наград / 30 дней). Промокод — скидка к тарифу. Условия могут измениться.'}
          </div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
            {theme.bonuses_referral_title || 'Ваша ссылка'}
          </div>
          <div style={{ fontSize: 10, color: muted, lineHeight: 1.45, marginBottom: 8 }}>
            {theme.bonuses_referral_hint || 'Скопируйте и отправьте другу'}
          </div>
          <input readOnly value="silentvpn://ref?code=ABCD1234" style={{
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 11, marginBottom: 6,
            borderRadius: 10, border: `1px solid ${fg}22`, background: `${fg}08`, color: fg,
          }} />
          <button type="button" style={{
            width: '100%', padding: '8px 0', borderRadius: 10, border: 'none', marginBottom: 14,
            background: theme.primary_color, color: bg, fontSize: 12, fontWeight: 600, cursor: 'default',
          }}>{theme.bonuses_copy_link_label || 'Копировать ссылку'}</button>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
            {theme.bonuses_promo_title || 'Промокод'}
          </div>
          <div style={{ fontSize: 10, color: muted, marginBottom: 8 }}>
            {theme.bonuses_promo_hint || 'Проверить скидку к тарифу'}
          </div>
          <input readOnly value="" placeholder="Введите код" style={{
            width: '100%', boxSizing: 'border-box', padding: '8px 10px', fontSize: 12,
            borderRadius: 10, border: `1px solid ${fg}22`, background: bg, color: fg,
          }} />
          <button type="button" style={{
            marginTop: 8, width: '100%', padding: '8px 0', borderRadius: 10, border: 'none',
            background: theme.primary_color, color: bg, fontSize: 12, fontWeight: 600, cursor: 'default',
          }}>Проверить</button>
          {!!(theme.bonuses_rules_text || '').trim() && (
            <div style={{ fontSize: 10, color: muted, lineHeight: 1.45, marginTop: 12, whiteSpace: 'pre-line' }}>
              {theme.bonuses_rules_text}
            </div>
          )}
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
        <>
          <p style={{ fontSize: 12, color: muted, lineHeight: 1.5, margin: '0 0 16px' }}>
            По вопросам обратитесь через Telegram.
          </p>
          <div style={{ display: 'flex', gap: 24 }}>
            {[
              { label: 'Канал', url: theme.telegram_channel_url || 'https://t.me/silentvpn3' },
              { label: 'Поддержка', url: theme.support_url || 'https://t.me/silentvpn3?direct' },
            ].map(({ label, url }) => (
              <div key={label} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 16, background: '#f3f4f6',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="#000">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z" />
                  </svg>
                </div>
                <span style={{ fontSize: 11, color: muted }}>{label}</span>
              </div>
            ))}
          </div>
        </>
      ))}

      {screen === 'about' && subPage('Silent VPN', (
        <div style={{ fontSize: 12, color: muted, lineHeight: 1.6 }}>
          <p style={{ margin: '0 0 6px' }}>Версия 1.0.144</p>
          <p style={{ margin: 0 }}>WireGuard-туннель через VK TURN/DTLS</p>
        </div>
      ))}
    </div>
  )

  return (
    <div>
      {!hideTabs && (
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
      )}
      <div style={{ transform: `scale(${scale})`, transformOrigin: 'top center', height: h * scale }}>
        {shell}
      </div>
      <p style={{ textAlign: 'center', fontSize: 11, color: '#666', marginTop: 8 }}>
        Единый UI для Android, iOS и PC · bootstrap-хеш в сборке, без шага VK
      </p>
    </div>
  )
}
