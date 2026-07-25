import { useEffect, useState } from 'react'
import { Settings } from 'lucide-react'

type ThreatStatus = {
  enabled: boolean
  wg_dns?: string
  domains_count?: number
  list_updated_at?: string | null
  list_source?: string
  note?: string
}

export default function ExtraSettingsPage({ token }: { token: string }) {
  const [disabled, setDisabled] = useState(false)
  const [message, setMessage] = useState(
    'Ведутся технические работы. Регистрация временно недоступна.'
  )
  const [threat, setThreat] = useState<ThreatStatus>({ enabled: false })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<'reg' | 'threat' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [regRes, threatRes] = await Promise.all([
        fetch('/api/admin/settings/registration', {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch('/api/admin/settings/threat-filter', {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ])
      const regData = await regRes.json().catch(() => ({}))
      const threatData = await threatRes.json().catch(() => ({}))
      if (!regRes.ok) {
        setError(regData.detail || 'Не удалось загрузить настройки регистрации')
        return
      }
      if (!threatRes.ok) {
        setError(threatData.detail || 'Не удалось загрузить фильтр угроз')
        return
      }
      setDisabled(!!regData.registration_disabled)
      if (typeof regData.message === 'string' && regData.message) setMessage(regData.message)
      setThreat({
        enabled: !!threatData.enabled,
        wg_dns: threatData.wg_dns,
        domains_count: threatData.domains_count ?? 0,
        list_updated_at: threatData.list_updated_at,
        list_source: threatData.list_source,
        note: threatData.note,
      })
    } catch {
      setError('Не удалось загрузить настройки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const toggleReg = async () => {
    setBusy('reg')
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
      setBusy(null)
    }
  }

  const toggleThreat = async () => {
    setBusy('threat')
    setError(null)
    setSuccess(null)
    const next = !threat.enabled
    try {
      const res = await fetch('/api/admin/settings/threat-filter', {
        method: 'POST',
        headers,
        body: JSON.stringify({ enabled: next }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Не удалось сохранить фильтр угроз')
        return
      }
      setThreat({
        enabled: !!data.enabled,
        wg_dns: data.wg_dns,
        domains_count: data.domains_count ?? 0,
        list_updated_at: data.list_updated_at,
        list_source: data.list_source,
        note: data.note,
      })
      setSuccess(
        data.enabled
          ? 'Фильтр угроз включён — клиентам нужен reconnect VPN для нового DNS'
          : 'Фильтр угроз выключен — DNS снова Яндекс (после reconnect)'
      )
    } finally {
      setBusy(null)
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
            disabled={loading || busy !== null}
            onClick={toggleReg}
            className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
              disabled ? 'bg-purple-500' : 'bg-[#333]'
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                disabled ? 'translate-x-4' : 'translate-x-0.5'
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

      <div className="rounded-xl border border-[#222] bg-[#111] p-5 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-medium text-white">Фильтр угроз (DNS)</h2>
            <p className="text-xs text-[#666] mt-1.5 leading-relaxed">
              Блокирует malware, phishing и scam по автообновляемому списку HaGeZi TIF на Улье.
              Без рекламных списков — меньше шанс сломать YouTube и игры. Если что-то перестало
              открываться — выключите тумблер и попросите пользователей переподключить VPN.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={threat.enabled}
            disabled={loading || busy !== null}
            onClick={toggleThreat}
            className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
              threat.enabled ? 'bg-purple-500' : 'bg-[#333]'
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                threat.enabled ? 'translate-x-4' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>

        <div className="rounded-lg border border-[#1e1e1e] bg-[#0d0d0d] px-3 py-2.5 space-y-1.5 text-xs text-[#888]">
          <p>
            DNS для клиентов:{' '}
            <span className="text-[#ccc] font-mono">{threat.wg_dns || '—'}</span>
          </p>
          <p>
            Список: {threat.list_source || 'HaGeZi TIF'} · доменов:{' '}
            <span className="text-[#ccc]">{threat.domains_count ?? 0}</span>
            {threat.list_updated_at ? (
              <>
                {' '}
                · обновлён: <span className="text-[#ccc]">{threat.list_updated_at}</span>
              </>
            ) : (
              <> · списки ещё не синхронизированы с хоста</>
            )}
          </p>
          {threat.note && <p className="text-[#555] leading-relaxed pt-1">{threat.note}</p>}
        </div>
      </div>
    </div>
  )
}
