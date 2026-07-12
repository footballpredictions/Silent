import { useState, useEffect } from 'react'
import ClientPreview, { SCREEN_TABS, type PreviewScreen } from '../components/ClientPreview'

const defaultTheme = {
  primary_color: '#000000', background_color: '#FFFFFF', text_color: '#000000',
  accent_color: '#1A1A1A', toggle_on_color: '#000000', toggle_off_color: '#CCCCCC',
  font_family: 'Inter', logo_url: '/static/logo.svg', app_name: 'Silent VPN',
  support_url: 'https://t.me/silentvpn3?direct', privacy_url: '', terms_url: '',
  telegram_channel_url: 'https://t.me/silentvpn3',
  telegram_proxy_url: '',
  telegram_proxy_menu_label: 'Ускорить Telegram',
  update_bar_background_color: '#2563EB', update_bar_text_color: '#FFFFFF',
  update_bar_progress_color: '#1D4ED8',
  update_bar_label_available: 'Доступно обновление', update_bar_label_downloading: 'Скачивание…',
  dark_primary_color: '', dark_background_color: '', dark_text_color: '',
  dark_accent_color: '', dark_toggle_on_color: '', dark_toggle_off_color: '',
  dark_update_bar_background_color: '', dark_update_bar_text_color: '',
  dark_update_bar_progress_color: '', dark_login_link_color: '',
  login_remember_me_label: 'Запомнить меня',
  login_forgot_password_label: 'Забыли пароль?',
  login_forgot_title: 'Восстановление пароля',
  login_forgot_instruction: 'Введите email — мы отправим ссылку для установки нового пароля.',
  login_link_color: '#4680C2',
  login_reset_title: 'Новый пароль',
  login_reset_button_text: 'Сохранить пароль',
  menu_bonuses_label: 'Бонусы',
  bonuses_title: 'Бонусы',
  bonuses_intro_text:
    'Рефералка: отправьте другу ссылку или код. Он регистрируется по ним и оплачивает любую подписку — оба получаете +30 дней. Один бонус на одного друга, до 10 наград за 30 дней.\n\nПромокод: отдельная скидка или доп. дни к тарифу — вводится при регистрации или проверяется здесь.\n\nУсловия программы могут измениться.',
  bonuses_referral_title: 'Ваша ссылка',
  bonuses_referral_hint: 'Скопируйте и отправьте другу',
  bonuses_promo_title: 'Промокод',
  bonuses_promo_hint: 'Проверить скидку к тарифу',
  bonuses_rules_text: '',
  bonuses_copy_link_label: 'Копировать ссылку',
  bonuses_copy_code_label: 'Копировать код',
  register_referral_or_promo_label: 'Промокод или реферальный код',
  register_referral_or_promo_hint: 'Необязательно. Введите промокод или код из реферальной ссылки.',
}

type Theme = typeof defaultTheme

/** Какие поля темы влияют на каждый экран предпросмотра */
const SCREEN_HINTS: Partial<Record<PreviewScreen, string>> = {
  login: 'Стартовый экран: bootstrap VPN автоматически (хеш в сборке). Табы «Войти» / «Регистрация». Поле промо/реф на регистрации.',
  login_forgot: 'Экран из приложения после «Забыли пароль?».',
  login_expired: 'Панель при истечении 2 мин bootstrap. Тексты пока в коде клиентов.',
  login_reset_web: 'HTML-страница из письма — открывается в браузере, не в приложении.',
  menu: 'Боковое меню: фон, текст, акцент, шрифт. Пункт «Бонусы». «Ускорить Telegram» если задан proxy URL.',
  subscription: 'Тарифы: основной цвет (кнопки), фон, текст.',
  exceptions: 'Список приложений (Android): фон, текст, основной цвет.',
  bonuses: 'Бонусы: реферальная ссылка + промокод. Тексты и подписи ниже.',
  devices: 'Сессии: фон, текст.',
  support: 'Поддержка: фон, текст. Два значка Telegram — канал и direct-поддержка.',
  about: 'О сервисе: фон, текст. Ссылки — политика и условия в «Главная».',
}

export default function ThemePage({ token }: { token: string }) {
  const [theme, setTheme] = useState<Theme>(defaultTheme)
  const [screen, setScreen] = useState<PreviewScreen>('login')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    fetch('/api/admin/theme', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json())
      .then(d => {
        const merged = { ...defaultTheme, ...d }
        // Устаревшие поля шага 1 не показываем в форме — при сохранении не отправляем
        const {
          login_step1_title: _a,
          login_step1_instruction: _b,
          login_hash_placeholder: _c,
          login_hash_button_text: _d,
          login_vk_mobile_url: _e,
          login_vk_mobile_link_text: _f,
          login_vk_pc_url: _g,
          login_vk_pc_link_text: _h,
          login_step2_title: _i,
          ...clean
        } = merged as Theme & Record<string, string>
        setTheme(clean as Theme)
      })
  }, [token])

  const save = async () => {
    setSaving(true)
    setMsg('')
    try {
      await fetch('/api/admin/theme', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(theme),
      })
      setMsg('Тема сохранена — клиенты подтянут при следующем входе')
    } catch {
      setMsg('Ошибка')
    }
    setSaving(false)
  }

  const field = (label: string, key: keyof Theme) => (
    <div key={key}>
      <label className="text-xs text-[#666] mb-1 block">{label}</label>
      {key.includes('color') ? (
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={theme[key]}
            onChange={e => setTheme({ ...theme, [key]: e.target.value })}
            className="w-10 h-10 rounded bg-transparent border border-[#2a2a2a] cursor-pointer"
          />
          <input
            type="text"
            value={theme[key]}
            onChange={e => setTheme({ ...theme, [key]: e.target.value })}
            className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none"
          />
        </div>
      ) : (
        <input
          type="text"
          value={theme[key]}
          onChange={e => setTheme({ ...theme, [key]: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-[#444]"
        />
      )}
    </div>
  )

  const fieldTextarea = (label: string, key: keyof Theme) => (
    <div key={String(key)}>
      <label className="text-xs text-[#666] mb-1 block">{label}</label>
      <textarea
        value={theme[key]}
        rows={3}
        onChange={e => setTheme({ ...theme, [key]: e.target.value })}
        className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-[#444] resize-y min-h-[72px]"
      />
    </div>
  )

  const colorFields = () => (
    <>
      {field('Основной цвет', 'primary_color')}
      {field('Фон', 'background_color')}
      {field('Цвет текста', 'text_color')}
    </>
  )

  const inheritedPanel = (hint: string) => (
    <div className="rounded-lg border border-[#2a2a2a] bg-[#0d0d0d] p-4 space-y-3">
      <p className="text-xs text-[#888] leading-relaxed">{hint}</p>
      <p className="text-[11px] text-[#555]">Настройки для этого экрана:</p>
      <div className="space-y-4">{colorFields()}</div>
      <button
        type="button"
        onClick={() => setScreen('main')}
        className="text-xs text-[#888] hover:text-white underline"
      >
        Все общие настройки → «Главная»
      </button>
    </div>
  )

  const settingsForScreen = () => {
    switch (screen) {
      case 'login':
        return (
          <div className="space-y-4">
            <p className="text-xs text-[#666]">{SCREEN_HINTS.login}</p>
            {field('«Запомнить меня»', 'login_remember_me_label')}
            {field('«Забыли пароль?»', 'login_forgot_password_label')}
            {field('Цвет ссылок', 'login_link_color')}
            {field('Подпись поля промо/реф', 'register_referral_or_promo_label')}
            {fieldTextarea('Подсказка промо/реф', 'register_referral_or_promo_hint')}
            {colorFields()}
          </div>
        )
      case 'login_forgot':
        return (
          <div className="space-y-4">
            <p className="text-xs text-[#666]">{SCREEN_HINTS.login_forgot}</p>
            {field('Заголовок', 'login_forgot_title')}
            {fieldTextarea('Инструкция', 'login_forgot_instruction')}
            {field('Цвет ссылок', 'login_link_color')}
            {colorFields()}
          </div>
        )
      case 'login_expired':
        return (
          <div className="space-y-4">
            <p className="text-xs text-[#888] leading-relaxed">{SCREEN_HINTS.login_expired}</p>
            {colorFields()}
          </div>
        )
      case 'login_reset_web':
        return (
          <div className="space-y-4">
            <p className="text-xs text-[#666]">{SCREEN_HINTS.login_reset_web}</p>
            {field('Заголовок', 'login_reset_title')}
            {field('Кнопка сохранения', 'login_reset_button_text')}
          </div>
        )
      case 'main':
        return (
          <div className="space-y-4">
            {field('Название приложения', 'app_name')}
            {field('Основной цвет', 'primary_color')}
            {field('Фон', 'background_color')}
            {field('Цвет текста', 'text_color')}
            {field('Акцентный цвет', 'accent_color')}
            {field('Тумблер (вкл)', 'toggle_on_color')}
            {field('Тумблер (выкл)', 'toggle_off_color')}
            {field('Шрифт', 'font_family')}
            <p className="text-xs text-[#888] pt-2">Тёмная тема (опционально — пусто = клиент сам инвертирует)</p>
            {field('Тёмный фон', 'dark_background_color')}
            {field('Тёмный текст', 'dark_text_color')}
            {field('Тёмный основной', 'dark_primary_color')}
            {field('Тёмный акцент', 'dark_accent_color')}
            {field('Тёмный тумблер вкл', 'dark_toggle_on_color')}
            {field('Тёмный тумблер выкл', 'dark_toggle_off_color')}
            {field('Тёмный цвет ссылок', 'dark_login_link_color')}
            {field('Тёмный фон update-bar', 'dark_update_bar_background_color')}
            {field('Тёмный текст update-bar', 'dark_update_bar_text_color')}
            {field('Тёмный прогресс update-bar', 'dark_update_bar_progress_color')}
            {field('URL логотипа', 'logo_url')}
            {field('URL поддержки (Telegram direct)', 'support_url')}
            {field('URL канала Telegram', 'telegram_channel_url')}
            {field('Telegram proxy URL (tg:// или t.me/proxy)', 'telegram_proxy_url')}
            {field('Пункт меню proxy', 'telegram_proxy_menu_label')}
            {field('URL политики конфиденциальности', 'privacy_url')}
            {field('URL условий использования', 'terms_url')}
          </div>
        )
      case 'main_update':
      case 'main_download':
        return (
          <div className="space-y-4">
            <p className="text-xs text-[#666]">
              {screen === 'main_download'
                ? 'Экран загрузки обновления — те же поля, что и «Обновление».'
                : 'Полоска внизу главного экрана вместо подписки.'}
            </p>
            {field('Фон полоски', 'update_bar_background_color')}
            {field('Цвет текста', 'update_bar_text_color')}
            {field('Цвет прогресса', 'update_bar_progress_color')}
            {field('Текст «доступно»', 'update_bar_label_available')}
            {field('Текст при загрузке', 'update_bar_label_downloading')}
          </div>
        )
      case 'menu':
        return (
          <div className="space-y-4">
            <p className="text-xs text-[#666]">{SCREEN_HINTS.menu}</p>
            {field('Фон', 'background_color')}
            {field('Цвет текста', 'text_color')}
            {field('Акцентный цвет', 'accent_color')}
            {field('Шрифт', 'font_family')}
            {field('Telegram proxy URL', 'telegram_proxy_url')}
            {field('Пункт меню «Ускорить Telegram»', 'telegram_proxy_menu_label')}
          </div>
        )
      case 'subscription':
      case 'exceptions':
      case 'devices':
      case 'support':
      case 'about':
        return inheritedPanel(SCREEN_HINTS[screen] || '')
      case 'bonuses':
        return (
          <div className="space-y-4">
            <p className="text-xs text-[#666]">{SCREEN_HINTS.bonuses}</p>
            {field('Пункт меню', 'menu_bonuses_label')}
            {field('Заголовок экрана', 'bonuses_title')}
            {fieldTextarea('Общее описание (реф + промо)', 'bonuses_intro_text')}
            {field('Заголовок рефералки', 'bonuses_referral_title')}
            {field('Подпись рефералки', 'bonuses_referral_hint')}
            {field('Заголовок промо', 'bonuses_promo_title')}
            {field('Подпись промо', 'bonuses_promo_hint')}
            {fieldTextarea('Доп. текст внизу (обычно пусто)', 'bonuses_rules_text')}
            {field('Кнопка копировать ссылку', 'bonuses_copy_link_label')}
            {colorFields()}
          </div>
        )
      default:
        return null
    }
  }

  const activeLabel = SCREEN_TABS.find(t => t.id === screen)?.label ?? screen

  return (
    <div className="space-y-5 max-w-5xl">
      <div>
        <h1 className="text-xl font-bold">Оформление клиентов</h1>
        <p className="text-[#555] text-sm mt-1">
          Вход без шага VK — bootstrap в сборке. Выберите экран: слева настройки, справа предпросмотр.
        </p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {SCREEN_TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            onClick={() => setScreen(id)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border ${
              screen === id
                ? 'bg-white text-black border-white'
                : 'bg-[#1a1a1a] text-[#888] border-[#333] hover:border-[#555] hover:text-[#ccc]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-[#111] border border-[#222] rounded-xl p-6 space-y-4">
          <h2 className="font-semibold text-sm text-white">
            Настройки: <span className="text-[#888]">{activeLabel}</span>
          </h2>
          {settingsForScreen()}
          <button
            onClick={save}
            disabled={saving}
            className="w-full bg-white text-black py-2.5 rounded-lg text-sm font-semibold hover:bg-[#e0e0e0] disabled:opacity-50 transition-colors mt-4"
          >
            {saving ? 'Сохраняем...' : 'Сохранить тему'}
          </button>
          {msg && <p className="text-center text-sm text-[#888]">{msg}</p>}
        </div>

        <div className="bg-[#111] border border-[#222] rounded-xl p-6">
          <h2 className="font-semibold mb-1 text-sm">Предпросмотр</h2>
          <p className="text-xs text-[#666] mb-4">{activeLabel}</p>
          <ClientPreview theme={theme} screen={screen} onScreenChange={setScreen} hideTabs />
        </div>
      </div>
    </div>
  )
}
