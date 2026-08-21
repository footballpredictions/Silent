import { useEffect, useState } from 'react'
import { Calendar } from 'lucide-react'
import SearchInput from '../components/SearchInput'

interface UserRow {
  id: string
  display_id: string
  email: string
  is_verified: boolean
  is_active: boolean
  is_admin?: boolean
  is_test_user?: boolean
  test_mode_excluded?: boolean
  in_test_mode?: boolean
  subscription: { active: boolean; plan: string | null; expires_at: string | null }
}

const PLANS = [
  { type: 'three_days', label: '3 дня',    days: 3 },
  { type: 'monthly',    label: 'Месяц',    days: 30 },
  { type: 'two_months', label: '2 месяца', days: 60 },
  { type: 'quarterly',  label: '3 месяца', days: 90 },
  { type: 'half_year',  label: 'Полгода',  days: 180 },
  { type: 'yearly',     label: 'Год',      days: 365 },
  { type: 'unlimited',  label: '∞',        days: null },
] as const

const PLAN_NAMES: Record<string, string> = {
  trial:      'Пробный',
  test:       'Тест',
  three_days: '3 дня',
  monthly:    'Месяц',
  two_months: '2 месяца',
  quarterly:  '3 месяца',
  half_year:  'Полгода',
  yearly:     'Год',
  unlimited:  '∞',
}

function subscriptionLabel(u: UserRow): string {
  const inTest = u.in_test_mode ?? u.is_test_user
  if (inTest || u.subscription.plan === 'test') return 'Тест · безлимит'
  if (u.is_admin || u.subscription.plan === 'unlimited') return '∞'
  if (!u.subscription.active) return 'Нет'
  const plan = PLAN_NAMES[u.subscription.plan || ''] || u.subscription.plan || 'Активна'
  const until = u.subscription.expires_at?.split('T')[0]
  return until ? `${plan} · до ${until}` : plan
}

export default function SubscriptionsPage({ token }: { token: string }) {
  const [users, setUsers] = useState<UserRow[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionKey, setActionKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [testMode, setTestMode] = useState(false)
  const [testModeBusy, setTestModeBusy] = useState(false)

  const headers = { Authorization: `Bearer ${token}` }

  const fetchTestMode = async () => {
    const res = await fetch('/api/admin/subscriptions/registration-test-mode', { headers })
    if (res.ok) {
      const data = await res.json()
      setTestMode(!!data.enabled)
    }
  }

  const fetchUsers = async () => {
    setLoading(true)
    setError(null)
    const res = await fetch('/api/admin/users', { headers })
    if (!res.ok) {
      setError('Не удалось загрузить пользователей')
      setLoading(false)
      return
    }
    setUsers(await res.json())
    setLoading(false)
  }

  useEffect(() => {
    fetchTestMode()
    fetchUsers()
  }, [])

  const toggleTestMode = async () => {
    setTestModeBusy(true)
    setError(null)
    setSuccess(null)
    const next = !testMode
    try {
      const res = await fetch('/api/admin/subscriptions/registration-test-mode', {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(body.detail || 'Не удалось изменить тестовый режим')
        return
      }
      setTestMode(!!body.enabled)
      const n = body.users_affected ?? 0
      setSuccess(
        body.enabled
          ? 'Глобальный тестовый режим включён — безлимит для всех пользователей'
          : `Глобальный тестовый режим выключен${n ? ` (очищено тест-подписок: ${n})` : ''}`
      )
      await fetchUsers()
    } finally {
      setTestModeBusy(false)
    }
  }

  const isPlanActive = (u: UserRow, planType: string) =>
    u.subscription.active && u.subscription.plan === planType

  const toggleUserTestMode = async (u: UserRow) => {
    const key = `${u.id}:test`
    setActionKey(key)
    setError(null)
    setSuccess(null)
    const currentlyInTest = u.in_test_mode ?? false
    const next = !currentlyInTest
    try {
      const res = await fetch(`/api/admin/users/${u.id}/test-mode`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: next }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(body.detail || 'Не удалось изменить тестовый режим пользователя')
        return
      }
      setSuccess(
        next
          ? `Безлимит включён для ${u.email}`
          : `Безлимит выключен для ${u.email}`
      )
      await fetchUsers()
    } finally {
      setActionKey(null)
    }
  }

  const togglePlan = async (u: UserRow, planType: string, planLabel: string) => {
    const key = `${u.id}:${planType}`
    setActionKey(key)
    setError(null)
    setSuccess(null)

    try {
      if (isPlanActive(u, planType)) {
        // Toggle OFF — revoke
        const res = await fetch(`/api/admin/users/${u.id}/revoke-subscription`, {
          method: 'POST',
          headers,
        })
        const body = await res.json().catch(() => ({}))
        if (!res.ok) {
          setError(body.detail || 'Не удалось отозвать подписку')
          return
        }
        setSuccess(`Подписка «${planLabel}» отозвана у ${u.email}`)
      } else {
        // Toggle ON — grant
        const res = await fetch(`/api/admin/users/${u.id}/grant-subscription`, {
          method: 'POST',
          headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({ plan_type: planType }),
        })
        const body = await res.json().catch(() => ({}))
        if (!res.ok) {
          setError(body.detail || 'Не удалось выдать подписку')
          return
        }
        const until = body.expires_at
          ? planType === 'unlimited'
            ? ''
            : ` · до ${body.expires_at.split('T')[0]}`
          : ''
        setSuccess(`Подписка «${planLabel}» выдана ${u.email}${until}`)
      }
      await fetchUsers()
    } finally {
      setActionKey(null)
    }
  }

  const filtered = users.filter(u =>
    !u.email.includes('bootstrap') && (
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      u.display_id.toLowerCase().includes(search.toLowerCase())
    )
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Calendar className="w-5 h-5" />
            Выдача подписок
          </h1>
          <p className="text-sm text-[#666] mt-1">Нажмите план чтобы выдать, повторно — чтобы забрать</p>
          <p className="text-xs text-[#555] mt-1">{loading ? '…' : `${filtered.length} из ${users.length}`}</p>
        </div>
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={toggleTestMode}
            disabled={testModeBusy}
            className={`flex items-center justify-between gap-3 px-4 py-2 rounded-lg border text-sm transition-colors disabled:opacity-50 ${
              testMode
                ? 'bg-purple-500/15 border-purple-500/50 text-purple-300'
                : 'bg-[#111] border-[#333] text-[#ccc] hover:border-[#555]'
            }`}
            title="Глобальный безлимит для всех пользователей"
          >
            <span className="font-medium">Тест (все)</span>
            <span
              className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors ${
                testMode ? 'bg-purple-500' : 'bg-[#333]'
              }`}
            >
              <span
                className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                  testMode ? 'translate-x-4' : 'translate-x-0.5'
                }`}
              />
            </span>
          </button>
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Поиск по email или ID…"
            className="w-full sm:w-56 shrink-0"
          />
        </div>
      </div>

      {testMode && (
        <div className="bg-purple-500/10 border border-purple-500/30 text-purple-300 text-sm rounded-lg px-4 py-3">
          Глобальный тестовый режим активен: все пользователи получают безлимит.
          Чтобы отключить одного — выключите его персональный переключатель в таблице.
        </div>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-500/10 border border-green-500/30 text-green-400 text-sm rounded-lg px-4 py-3">
          {success}
        </div>
      )}

      <div className="bg-[#111] border border-[#222] rounded-xl overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead>
            <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">ID</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Текущая подписка</th>
              <th className="text-left px-4 py-3">Статус</th>
              <th className="text-center px-4 py-3">Тест</th>
              <th className="px-4 py-3 text-right">Планы</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="text-center py-12 text-[#555]">Загрузка...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-12 text-[#555]">Нет пользователей</td></tr>
            ) : (
              filtered.map(u => (
                <tr key={u.id} className="border-b border-[#1a1a1a] hover:bg-[#151515] transition-colors">
                  <td className="px-4 py-3 font-mono text-[#888]">{u.display_id}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>{u.email}</span>
                      {u.is_test_user && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/40">
                          Личный
                        </span>
                      )}
                      {u.test_mode_excluded && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300/90 border border-amber-500/30">
                          Исключён
                        </span>
                      )}
                      {(u.in_test_mode ?? false) && testMode && !u.is_test_user && !u.test_mode_excluded && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400/80 border border-purple-500/25">
                          Глоб.
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs ${u.subscription.active || u.is_admin || (u.in_test_mode ?? u.is_test_user) ? 'text-green-400' : 'text-[#555]'}`}>
                      {subscriptionLabel(u)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-1 text-xs">
                      <span className={u.is_active ? 'text-green-400/80' : 'text-red-400/80'}>
                        {u.is_active ? 'Активен' : 'Заблокирован'}
                      </span>
                      <span className={u.is_verified ? 'text-green-400/80' : 'text-amber-400/80'}>
                        {u.is_verified ? 'Верифицирован' : 'Не верифицирован'}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    {u.is_admin ? (
                      <span className="text-xs text-[#555]">—</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => toggleUserTestMode(u)}
                        disabled={actionKey === `${u.id}:test`}
                        title={
                          (u.in_test_mode ?? false)
                            ? 'Выключить безлимит для этого пользователя'
                            : 'Включить безлимит для этого пользователя'
                        }
                        className="inline-flex items-center disabled:opacity-40"
                      >
                        <span
                          className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors ${
                            (u.in_test_mode ?? false) ? 'bg-purple-500' : 'bg-[#333]'
                          }`}
                        >
                          <span
                            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                              (u.in_test_mode ?? false) ? 'translate-x-4' : 'translate-x-0.5'
                            }`}
                          />
                        </span>
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {u.is_admin ? (
                      <div className="text-right text-xs font-semibold text-amber-400/90">Админ</div>
                    ) : (u.in_test_mode ?? false) ? (
                      <div className="text-right text-xs font-semibold text-purple-300/90">Тест · ∞</div>
                    ) : (
                      <div className="flex items-center justify-end gap-1.5 flex-wrap">
                        {PLANS.map(p => {
                          const active = isPlanActive(u, p.type)
                          const busy = actionKey === `${u.id}:${p.type}`
                          return (
                            <button
                              key={p.type}
                              onClick={() => togglePlan(u, p.type, p.label)}
                              disabled={busy}
                              title={active
                                ? `Забрать «${p.label}»`
                                : `Выдать «${p.label}»${p.days ? ` (${p.days} дн.)` : ''}`}
                              className={`px-2.5 py-1 rounded-lg text-xs border transition-colors disabled:opacity-40 ${
                                active
                                  ? 'bg-green-500/20 border-green-500/60 text-green-400 hover:bg-red-500/20 hover:border-red-500/60 hover:text-red-400'
                                  : 'border-[#333] text-[#ccc] hover:bg-white hover:text-black hover:border-white'
                              }`}
                            >
                              {busy ? '…' : p.label}
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
