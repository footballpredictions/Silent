import { useState, useEffect } from 'react'
import ClientPreview from '../components/ClientPreview'

const defaultTheme = {
  primary_color: '#000000', background_color: '#FFFFFF', text_color: '#000000',
  accent_color: '#1A1A1A', toggle_on_color: '#000000', toggle_off_color: '#CCCCCC',
  font_family: 'Inter', logo_url: '/static/logo.svg', app_name: 'Silent VPN',
  support_url: '', privacy_url: '', terms_url: '',
}

export default function ThemePage({ token }: { token: string }) {
  const [theme, setTheme] = useState(defaultTheme)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    fetch('/api/admin/theme', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(d => setTheme({ ...defaultTheme, ...d }))
  }, [])

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      await fetch('/api/admin/theme', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(theme),
      })
      setMsg('Тема сохранена — клиенты подтянут при следующем входе')
    } catch { setMsg('Ошибка') }
    setSaving(false)
  }

  const field = (label: string, key: keyof typeof theme) => (
    <div key={key}>
      <label className="text-xs text-[#666] mb-1 block">{label}</label>
      {key.includes('color') ? (
        <div className="flex items-center gap-2">
          <input type="color" value={theme[key]} onChange={e => setTheme({ ...theme, [key]: e.target.value })}
            className="w-10 h-10 rounded bg-transparent border border-[#2a2a2a] cursor-pointer" />
          <input type="text" value={theme[key]} onChange={e => setTheme({ ...theme, [key]: e.target.value })}
            className="flex-1 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none" />
        </div>
      ) : (
        <input type="text" value={theme[key]} onChange={e => setTheme({ ...theme, [key]: e.target.value })}
          className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-[#444]" />
      )}
    </div>
  )

  return (
    <div className="space-y-6 max-w-4xl">
      <h1 className="text-xl font-bold">Оформление клиентов</h1>
      <p className="text-[#555] text-sm">
        Тема хранится на сервере и применяется на Android, iOS и PC. Предпросмотр ниже — тот же макет, что в приложениях.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-[#111] border border-[#222] rounded-xl p-6 space-y-4">
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

          <button onClick={save} disabled={saving}
            className="w-full bg-white text-black py-2.5 rounded-lg text-sm font-semibold hover:bg-[#e0e0e0] disabled:opacity-50 transition-colors mt-2">
            {saving ? 'Сохраняем...' : 'Сохранить тему'}
          </button>
          {msg && <p className="text-center text-sm text-[#888]">{msg}</p>}
        </div>

        <div className="bg-[#111] border border-[#222] rounded-xl p-6">
          <h2 className="font-semibold mb-4 text-sm">Предпросмотр клиента</h2>
          <p className="text-xs text-[#666] mb-4">
            Переключайте экраны: главная, меню и каждый раздел бокового меню приложения
          </p>
          <ClientPreview theme={theme} />
        </div>
      </div>
    </div>
  )
}
