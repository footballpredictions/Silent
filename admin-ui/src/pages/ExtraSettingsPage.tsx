import { useEffect, useRef, useState } from 'react'
import { Settings } from 'lucide-react'
import RoutingPolicySettings from '../components/RoutingPolicySettings'

type ThreatStatus = {
  enabled: boolean
  wg_dns?: string
  domains_count?: number
  list_updated_at?: string | null
  list_source?: string
  note?: string
}

type CleanupPreview = { candidate_users: number; candidate_devices: number; cutoff: string; batch_limit: number }

type CleanupStatus = {
  enabled: boolean
  interval_days?: number
  journal_max_mb?: number
  run_now?: boolean
  last_run_at?: string | null
  last_summary?: string | null
  note?: string
  inactive_users_enabled?: boolean
  status?: string
  started_at?: string | null
  error?: string | null
  result?: { steps?: { name: string; status: string; error?: string }[] }
}

export default function ExtraSettingsPage({ token }: { token: string }) {
  const [disabled, setDisabled] = useState(false)
  const [skipEmailConfirm, setSkipEmailConfirm] = useState(false)
  const [message, setMessage] = useState(
    'Ведутся технические работы. Регистрация временно недоступна.'
  )
  const [threat, setThreat] = useState<ThreatStatus>({ enabled: false })
  const [cleanup, setCleanup] = useState<CleanupStatus>({
    enabled: false,
    interval_days: 7,
    journal_max_mb: 200,
  })
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<'reg' | 'skipMail' | 'threat' | 'cleanup' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [cleanupPollError, setCleanupPollError] = useState<string | null>(null)
  const [cleanupConfirm, setCleanupConfirm] = useState<{ patch: Partial<CleanupStatus> & { enabled: boolean }; preview: CleanupPreview } | null>(null)
  const cleanupDialog = useRef<HTMLDialogElement>(null)
  const cleanupRunning = cleanup.run_now || cleanup.status === 'queued' || cleanup.status === 'running'

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [regRes, threatRes, cleanupRes] = await Promise.all([
        fetch('/api/admin/settings/registration', {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch('/api/admin/settings/threat-filter', {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch('/api/admin/settings/vps-cleanup', {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ])
      const regData = await regRes.json().catch(() => ({}))
      const threatData = await threatRes.json().catch(() => ({}))
      const cleanupData = await cleanupRes.json().catch(() => ({}))
      if (!regRes.ok) {
        setError(regData.detail || 'Не удалось загрузить настройки регистрации')
        return
      }
      if (!threatRes.ok) {
        setError(threatData.detail || 'Не удалось загрузить фильтр угроз')
        return
      }
      if (!cleanupRes.ok) {
        setError(cleanupData.detail || 'Не удалось загрузить автоочистку')
        return
      }
      setDisabled(!!regData.registration_disabled)
      setSkipEmailConfirm(!!regData.skip_email_confirmation)
      if (typeof regData.message === 'string' && regData.message) setMessage(regData.message)
      setThreat({
        enabled: !!threatData.enabled,
        wg_dns: threatData.wg_dns,
        domains_count: threatData.domains_count ?? 0,
        list_updated_at: threatData.list_updated_at,
        list_source: threatData.list_source,
        note: threatData.note,
      })
      setCleanup({
        ...cleanupData,
        enabled: !!cleanupData.enabled,
        interval_days: cleanupData.interval_days ?? 7,
        journal_max_mb: cleanupData.journal_max_mb ?? 200,
        run_now: !!cleanupData.run_now,
        last_run_at: cleanupData.last_run_at,
        last_summary: cleanupData.last_summary,
        note: cleanupData.note,
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

  useEffect(() => {
    if (loading) return
    let cancelled = false
    const timer = window.setInterval(async () => {
      if (busy === 'cleanup') return
      try {
        const response = await fetch('/api/admin/settings/vps-cleanup', { headers: { Authorization: `Bearer ${token}` } })
        if (!response.ok) throw new Error('poll')
        const data: CleanupStatus = await response.json()
        if (!cancelled) {
          setCleanup(current => ({ ...data, interval_days: current.interval_days, journal_max_mb: current.journal_max_mb }))
          setCleanupPollError(null)
        }
      } catch {
        if (!cancelled) setCleanupPollError('Не удалось обновить статус. Повторяем проверку автоматически.')
      }
    }, cleanupRunning ? 3000 : 15000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [token, loading, busy, cleanupRunning])

  useEffect(() => {
    if (cleanupConfirm && !cleanupDialog.current?.open) cleanupDialog.current?.showModal()
    if (!cleanupConfirm && cleanupDialog.current?.open) cleanupDialog.current.close()
  }, [cleanupConfirm])

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
      if (typeof data.skip_email_confirmation === 'boolean') {
        setSkipEmailConfirm(data.skip_email_confirmation)
      }
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

  const toggleSkipMail = async () => {
    setBusy('skipMail')
    setError(null)
    setSuccess(null)
    const next = !skipEmailConfirm
    try {
      const res = await fetch('/api/admin/settings/registration', {
        method: 'POST',
        headers,
        body: JSON.stringify({ skip_email_confirmation: next }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Не удалось сохранить')
        return
      }
      setDisabled(!!data.registration_disabled)
      setSkipEmailConfirm(!!data.skip_email_confirmation)
      if (typeof data.message === 'string' && data.message) setMessage(data.message)
      setSuccess(
        data.skip_email_confirmation
          ? 'Подтверждение почты выключено — после регистрации можно сразу войти'
          : 'Подтверждение почты снова требуется'
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

  const saveCleanup = async (patch: Partial<CleanupStatus> & { enabled: boolean }) => {
    setBusy('cleanup')
    setError(null)
    setSuccess(null)
    try {
      const res = await fetch('/api/admin/settings/vps-cleanup', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          enabled: patch.enabled,
          interval_days: patch.interval_days ?? cleanup.interval_days ?? 7,
          journal_max_mb: patch.journal_max_mb ?? cleanup.journal_max_mb ?? 200,
          run_now: patch.run_now,
          inactive_users_enabled: patch.inactive_users_enabled ?? cleanup.inactive_users_enabled ?? false,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(data.detail || 'Не удалось сохранить автоочистку')
        return false
      }
      setCleanup({
        ...data,
        enabled: !!data.enabled,
        interval_days: data.interval_days ?? 7,
        journal_max_mb: data.journal_max_mb ?? 200,
        run_now: !!data.run_now,
        last_run_at: data.last_run_at,
        last_summary: data.last_summary,
        note: data.note,
      })
      if (patch.run_now) {
        setSuccess('Запуск запрошен. Статус и результат появятся в карточке очистки.')
      } else if (data.enabled && !cleanup.enabled) {
        setSuccess('Автоочистка включена — первый прогон скоро на Улье')
      } else if (!data.enabled) {
        setSuccess('Автоочистка выключена')
      } else {
        setSuccess('Параметры автоочистки сохранены')
      }
      setCleanupPollError(null)
      return true
    } catch {
      setError('Не удалось сохранить автоочистку. Повторите попытку.')
      return false
    } finally {
      setBusy(null)
    }
  }

  const requestCleanup = async (patch: Partial<CleanupStatus> & { enabled: boolean }) => {
    const deletesUsers = patch.inactive_users_enabled ?? cleanup.inactive_users_enabled
    if (!deletesUsers || !(patch.run_now || (patch.enabled && !cleanup.enabled) || patch.inactive_users_enabled === true)) {
      await saveCleanup(patch)
      return
    }
    setBusy('cleanup')
    setError(null)
    try {
      const response = await fetch('/api/admin/settings/vps-cleanup/inactive-preview', { headers: { Authorization: `Bearer ${token}` } })
      if (!response.ok) throw new Error('preview')
      const preview: CleanupPreview = await response.json()
      setCleanupConfirm({ patch, preview })
    } catch {
      setError('Не удалось проверить неактивные аккаунты. Очистка не запущена; повторите попытку.')
    } finally { setBusy(null) }
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

      <RoutingPolicySettings token={token} />

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
            <h2 className="text-sm font-medium text-white">Отключить подтверждение почты</h2>
            <p className="text-xs text-[#666] mt-1.5 leading-relaxed">
              При включении новые аккаунты сразу считаются подтверждёнными — письмо не
              отправляется, вход работает без ссылки из почты. Уже зарегистрированные, но
              не подтвердившие email, тоже смогут войти. Выключите, когда SMTP снова
              стабилен.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={skipEmailConfirm}
            disabled={loading || busy !== null}
            onClick={toggleSkipMail}
            className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
              skipEmailConfirm ? 'bg-purple-500' : 'bg-[#333]'
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                skipEmailConfirm ? 'translate-x-4' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>
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

      <div className="rounded-xl border border-[#222] bg-[#111] p-5 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-medium text-white">Автоочистка Улья (диск)</h2>
            <p className="text-xs text-[#666] mt-1.5 leading-relaxed">
              По расписанию или вручную: старые журналы, кеш пакетов и сборки,
              устаревшие временные скрипты. Удаление неактивных аккаунтов включается отдельно.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-label="Автоочистка Улья по расписанию"
            aria-checked={cleanup.enabled}
            disabled={loading || busy !== null}
            onClick={() => void requestCleanup({ enabled: !cleanup.enabled })}
            className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-50 ${
              cleanup.enabled ? 'bg-purple-500' : 'bg-[#333]'
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                cleanup.enabled ? 'translate-x-4' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs text-[#888] space-y-1">
            <span>Интервал (дней)</span>
            <input
              type="number"
              min={1}
              max={30}
              value={cleanup.interval_days ?? 7}
              disabled={loading || busy !== null}
              onChange={(e) =>
                setCleanup((c) => ({
                  ...c,
                  interval_days: Math.max(1, Math.min(30, Number(e.target.value) || 7)),
                }))
              }
              className="w-full rounded-lg border border-[#333] bg-[#0d0d0d] px-3 py-2 text-sm text-white disabled:opacity-40"
            />
          </label>
          <label className="text-xs text-[#888] space-y-1">
            <span>Journal max (МБ)</span>
            <input
              type="number"
              min={50}
              max={2000}
              step={50}
              value={cleanup.journal_max_mb ?? 200}
              disabled={loading || busy !== null}
              onChange={(e) =>
                setCleanup((c) => ({
                  ...c,
                  journal_max_mb: Math.max(50, Math.min(2000, Number(e.target.value) || 200)),
                }))
              }
              className="w-full rounded-lg border border-[#333] bg-[#0d0d0d] px-3 py-2 text-sm text-white disabled:opacity-40"
            />
          </label>
        </div>

        <label className="flex items-start gap-3 text-sm text-[#ccc]">
          <input
            type="checkbox"
            checked={!!cleanup.inactive_users_enabled}
            disabled={loading || busy !== null || !!cleanupRunning}
            onChange={event => void requestCleanup({ enabled: cleanup.enabled, inactive_users_enabled: event.target.checked, run_now: false })}
            className="mt-1 accent-purple-500"
          />
          <span>
            Удалять аккаунты без активности более 3 месяцев
            <span className="block mt-1 text-xs text-[#aaa] leading-relaxed">
              Действующие подписки, администраторы и живые VPN-подключения сохраняются.
              Перед удалением проверяются все серверы.
            </span>
          </span>
        </label>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={loading || busy !== null}
            onClick={() =>
              void saveCleanup({
                enabled: cleanup.enabled,
                interval_days: cleanup.interval_days,
                journal_max_mb: cleanup.journal_max_mb,
                run_now: false,
              })
            }
            className="rounded-lg border border-[#333] bg-[#1a1a1a] px-3 py-1.5 text-xs text-[#ccc] hover:bg-[#222] disabled:opacity-40"
          >
            Сохранить параметры
          </button>
          <button
            type="button"
            disabled={loading || busy !== null || !!cleanupRunning}
            onClick={() =>
              void requestCleanup({
                enabled: cleanup.enabled,
                interval_days: cleanup.interval_days,
                journal_max_mb: cleanup.journal_max_mb,
                run_now: true,
              })
            }
            className="rounded-lg border border-purple-800/60 bg-purple-950/40 px-3 py-1.5 text-xs text-purple-200 hover:bg-purple-950/70 disabled:opacity-40"
          >
            Очистить сейчас
          </button>
        </div>

        <div aria-live="polite" className="rounded-lg border border-[#1e1e1e] bg-[#0d0d0d] px-3 py-2.5 space-y-1.5 text-xs text-[#aaa]">
          <p>
            Статус:{' '}
            <span className="text-[#ccc]">
              {({ queued: 'В очереди', running: 'Выполняется', succeeded: 'Завершено', partial: 'Завершено частично', failed: 'Ошибка' } as Record<string, string>)[cleanup.status || ''] || (cleanup.run_now ? 'В очереди' : 'Ожидает запуска')}
            </span>
            {' · '}
            {cleanup.enabled ? `расписание: раз в ${cleanup.interval_days ?? 7} дн.` : 'расписание выключено'}
          </p>
          {cleanup.status === 'running' && cleanup.started_at && <p>Начало: {new Date(cleanup.started_at).toLocaleString('ru-RU')}</p>}
          <p>
            Последний прогон:{' '}
            <span className="text-[#ccc]">{cleanup.last_run_at ? new Date(cleanup.last_run_at).toLocaleString('ru-RU') : 'ещё не было'}</span>
          </p>
          {cleanup.last_summary && (
            <p className="text-xs text-[#ccc] break-words">{cleanup.last_summary}</p>
          )}
          {(cleanup.error || cleanupPollError) && <p role="alert" className="text-red-400 break-words">{cleanup.error || cleanupPollError}</p>}
          {cleanup.result?.steps?.filter(step => step.status === 'error').map(step => <p key={step.name} className="text-red-400 break-words">{step.error}</p>)}
          {cleanup.note && <p className="text-[#555] leading-relaxed pt-1">{cleanup.note}</p>}
        </div>
      </div>
      <dialog
        ref={cleanupDialog}
        role="alertdialog"
        aria-labelledby="cleanup-confirm-title"
        aria-describedby="cleanup-confirm-description"
        onCancel={event => { if (busy === 'cleanup') event.preventDefault(); else setCleanupConfirm(null) }}
        onClose={() => setCleanupConfirm(null)}
        className="!m-auto w-[calc(100%_-_2rem)] max-w-md rounded-xl border border-[#222] bg-[#111] p-6 text-[#e5e7eb] backdrop:bg-black/70"
      >
        <h2 id="cleanup-confirm-title" className="text-lg font-semibold">{cleanupConfirm?.patch.run_now ? 'Запустить очистку аккаунтов?' : 'Включить очистку аккаунтов?'}</h2>
        <div id="cleanup-confirm-description" className="mt-3 space-y-3 text-sm text-[#aaa] leading-relaxed">
          <p>Без активности с {cleanupConfirm && new Date(cleanupConfirm.preview.cutoff).toLocaleDateString('ru-RU')}: предварительно {cleanupConfirm?.preview.candidate_users ?? 0} аккаунтов и {cleanupConfirm?.preview.candidate_devices ?? 0} устройств.</p>
          <p>Действующие подписки и живые подключения защищены. Если проверка хотя бы одного сервера не удалась, аккаунты не удаляются.</p>
          <p>Аккаунты и их данные удаляются без восстановления, до {cleanupConfirm?.preview.batch_limit ?? 100} аккаунтов за запуск. {cleanupConfirm?.patch.run_now ? 'Очистка начнётся сейчас.' : 'Удаление будет выполняться вместе с очисткой по расписанию или вручную.'}</p>
        </div>
        {error && <p role="alert" className="mt-3 text-sm text-red-400">{error}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" autoFocus disabled={busy === 'cleanup'} onClick={() => setCleanupConfirm(null)} className="rounded-lg border border-[#333] bg-[#1a1a1a] px-4 py-2 text-sm hover:bg-[#222] disabled:opacity-50">Отмена</button>
          <button type="button" disabled={busy === 'cleanup'} onClick={async () => { if (cleanupConfirm && await saveCleanup(cleanupConfirm.patch)) setCleanupConfirm(null) }} className="rounded-lg border border-red-500/30 bg-red-500/15 px-4 py-2 text-sm text-red-400 hover:bg-red-500/25 disabled:opacity-50">
            {busy === 'cleanup' ? 'Сохраняем…' : cleanupConfirm?.patch.run_now ? 'Запустить' : 'Включить'}
          </button>
        </div>
      </dialog>
    </div>
  )
}
