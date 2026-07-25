import { useEffect, useState } from 'react'
import { Settings } from 'lucide-react'

export default function ExtraSettingsPage({ token }: { token: string }) {
  const [disabled, setDisabled] = useState(false)
  const [message, setMessage] = useState(
    'Ведутся технические работы. Регистрация временно недоступна.'
  )
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/admin/settings/registration', {
        headers: { Authorization: `Bearer ${token}` },
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Не удалось загрузить настройки')
        return
      }
      setDisabled(!!data.registration_disabled)
      if (typeof data.message === 'string' && data.message) setMessage(data.message)
    } catch {
      setError('Не удалось загрузить настройки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const toggle = async () => {
    setBusy(true)
    setError(null)
    setSuccess(null)
    const next = !disabled
    try {
      const res = await fetch('/api/admin/settings/registration', {
        method: 'POST',
        headers,
        body: JSON.stringify({ disabled: next }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Не удалось сохранить')
        return
      }
      setDisabled(!!data.registration_disabled)
      if (typeof data.message === 'string' && data.message) setMessage(data.message)
      setSuccess(
        data.registration_disabled
          ? 'Регистрация отключена — новые пользователи увидят сообщение о техработах'
          : 'Регистрация снова открыта'
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex items-center gap-3">
        <Settings className="w-6 h-6 text-[#888]" />
        <div>
          <h1 className="text-xl font-bold">Дополнительные настройки</h1>
          <p className="text-sm text-[#666] mt-0.5">
            Оперативные переключатели при сбоях и техработах
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-900/50 bg-red-950/30 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-emerald-900/50 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-300">
          {success}
        </div>
      )}

      <div className="rounded-xl border border-[#222] bg-[#111] p-5 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-medium text-white">Отключить регистрацию</h2>
            <p className="text-xs text-[#666] mt-1.5 leading-relaxed">
              При включении новые аккаунты не создаются. Вход для уже зарегистрированных
              пользователей не затрагивается. Используйте при сбое, когда люди регистрируются,
              но не могут нормально пользоваться сервисом.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={disabled}
            disabled={loading || busy}
            onClick={toggle}
            className={`relative shrink-0 w-11 h-6 rounded-full transition-colors disabled:opacity-50 ${
              disabled ? 'bg-amber-500' : 'bg-[#333]'
            }`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${
                disabled ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        {disabled && (
          <div className="rounded-lg border border-amber-900/40 bg-amber-950/20 px-3 py-2.5">
            <p className="text-[11px] uppercase tracking-wide text-amber-500/80 mb-1">
              Текст для пользователя
            </p>
            <p className="text-sm text-amber-100/90 leading-relaxed">{message}</p>
          </div>
        )}
      </div>
    </div>
  )
}
