import { useState, useEffect } from 'react'
import ClientPreview, { SCREEN_TABS, type PreviewScreen } from '../components/ClientPreview'

const defaultTheme = {
  primary_color: '#000000', background_color: '#FFFFFF', text_color: '#000000',
  accent_color: '#1A1A1A', toggle_on_color: '#000000', toggle_off_color: '#CCCCCC',
  font_family: 'Inter', logo_url: '/static/logo.svg', app_name: 'Silent VPN',
  support_url: '', privacy_url: '', terms_url: '',
  update_bar_background_color: '#2563EB', update_bar_text_color: '#FFFFFF',
  update_bar_progress_color: '#1D4ED8',
  update_bar_label_available: 'Доступно обновление', update_bar_label_downloading: 'Скачивание…',
  login_step1_title: 'Шаг 1 — хеш звонка VK',
  login_step1_instruction: 'Скопируйте хеш из раздела «Звонки» в приложении ВКонтакте (на ПК — VK Звонки в браузере). Вставьте хеш или ссылку ниже — временный канал только для входа или регистрации (2 мин).',
  login_hash_placeholder: 'Хеш или ссылка на звонок VK',
  login_hash_button_text: 'Подтвердить',
  login_vk_mobile_url: 'https://vk.com/calls',
  login_vk_mobile_link_text: 'ВКонтакте — раздел «Звонки»',
  login_vk_pc_url: 'https://vk.com/calls',
  login_vk_pc_link_text: 'VK Звонки в браузере',
  login_link_color: '#4680C2',
  login_step2_title: 'Шаг 2 — вход или регистрация',
  login_remember_me_label: 'Запомнить меня',
  login_forgot_password_label: 'Забыли пароль?',
  login_forgot_title: 'Восстановление пароля',
  login_forgot_instruction: 'Введите email — мы отправим ссылку для установки нового пароля.',
  login_reset_title: 'Новый пароль',
  login_reset_button_text: 'Сохранить пароль',
}

type Theme = typeof defaultTheme

/** Какие поля темы влияют на каждый экран предпросмотра */
const SCREEN_HINTS: Partial<Record<PreviewScreen, string>> = {
  menu: 'Боковое меню: фон, текст, акцент, шрифт.',
  subscription: 'Тарифы: основной цвет (кнопки), фон, текст.',
  exceptions: 'Список приложений: фон, текст, основной цвет.',
  hashes: 'Список хешей: фон, текст.',
  promo: 'Промокод: основной цвет (кнопка), фон, текст.',
  devices: 'Сессии: фон, текст.',
  support: 'Поддержка: фон, текст. Ссылка — URL поддержки в «Главная».',
  about: 'О сервисе: фон, текст. Ссылки — политика и условия в «Главная».',
}

export default function ThemePage({ token }: { token: string }) {
  const [theme, setTheme] = useState<Theme>(defaultTheme)
  const [screen, setScreen] = useState<PreviewScreen>('main')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    fetch('/api/admin/theme', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(d => setTheme({ ...defaultTheme, ...d }))
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

  const inheritedPanel = (hint: string) => (
    <div className="rounded-lg border border-[#2a2a2a] bg-[#0d0d0d] p-4 space-y-3">
      <p className="text-xs text-[#888] leading-relaxed">{hint}</p>
      <p className="text-[11px] text-[#555]">Настройки для этого экрана:</p>
      <div className="space-y-4">
        {field('Основной цвет', 'primary_color')}
        {field('Фон', 'background_color')}
        {field('Цвет текста', 'text_color')}
      </div>
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
            {field('URL логотипа', 'logo_url')}
            {field('URL поддержки', 'support_url')}
            {field('URL политики конфиденциальности', 'privacy_url')}
            {field('URL условий использования', 'terms_url')}
          </div>
        )
      case 'login_step1':
        return (
          <div className="space-y-4">
            {field('Заголовок', 'login_step1_title')}
            {fieldTextarea('Инструкция', 'login_step1_instruction')}
            {field('Placeholder поля хеша', 'login_hash_placeholder')}
            {field('Кнопка подтверждения', 'login_hash_button_text')}
            {field('Ссылка (моб.) — URL', 'login_vk_mobile_url')}
            {field('Ссылка (моб.) — текст', 'login_vk_mobile_link_text')}
            {field('Ссылка (ПК) — URL', 'login_vk_pc_url')}
            {field('Ссылка (ПК) — текст', 'login_vk_pc_link_text')}
            {field('Цвет ссылок', 'login_link_color')}
            {field('Основной цвет (кнопка)', 'primary_color')}
            {field('Фон', 'background_color')}
            {field('Цвет текста', 'text_color')}
          </div>
        )
      case 'login_step2':
        return (
          <div className="space-y-4">
            {field('Заголовок', 'login_step2_title')}
            {field('«Запомнить меня»', 'login_remember_me_label')}
            {field('«Забыли пароль?»', 'login_forgot_password_label')}
            {field('Заголовок восстановления', 'login_forgot_title')}
            {fieldTextarea('Текст восстановления', 'login_forgot_instruction')}
            {field('Заголовок нового пароля', 'login_reset_title')}
            {field('Кнопка сохранения пароля', 'login_reset_button_text')}
            {field('Цвет ссылок', 'login_link_color')}
            {field('Основной цвет (кнопка)', 'primary_color')}
            {field('Фон', 'background_color')}
            {field('Цвет текста', 'text_color')}
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
          </div>
        )
      case 'subscription':
      case 'exceptions':
      case 'hashes':
      case 'promo':
      case 'devices':
      case 'support':
      case 'about':
        return inheritedPanel(SCREEN_HINTS[screen] || '')
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
          Выберите экран — справа предпросмотр, слева только его настройки.
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
