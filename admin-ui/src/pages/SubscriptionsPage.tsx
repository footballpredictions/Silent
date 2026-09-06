import { useEffect, useState } from 'react'
import { Calendar, KeyRound, X, ChevronLeft, ChevronRight, AlertTriangle } from 'lucide-react'
import SearchInput from '../components/SearchInput'
import SortSelect from '../components/SortSelect'

interface SubInfo {
  active: boolean
  plan: string | null
  expires_at: string | null
  started_at?: string | null
}

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
  subscription: SubInfo
  payments_completed?: number
}

interface PaymentRow {
  id: string
  plan_type: string
  amount: number
  paid_amount: number | null
  status: string
  support_code: string | null
  subscription_applied: boolean
  manual_activated_at: string | null
  yumoney_label: string
  created_at: string
  completed_at: string | null
}

interface HistoryPayload {
  user: UserRow
  payments: PaymentRow[]
  subscriptions: Array<{
    id: string
    plan_type: string
    status: string
    amount_paid: number
    started_at: string
    expires_at: string
    is_active_now: boolean
    promo_code: string | null
  }>
}

interface CodeLookup {
  payment: PaymentRow
  user: UserRow
  needs_activation: boolean
  status?: string
  expires_at?: string
}

const PLANS = [
  { type: 'three_days', label: '3 дня', days: 3 },
  { type: 'monthly', label: 'Месяц', days: 30 },
  { type: 'two_months', label: '2 месяца', days: 60 },
  { type: 'quarterly', label: '3 месяца', days: 90 },
  { type: 'half_year', label: 'Полгода', days: 180 },
  { type: 'yearly', label: 'Год', days: 365 },
  { type: 'unlimited', label: '∞', days: null },
] as const

const SUB_FILTER_KEY = 'admin.subscriptions.filter'

const SUB_FILTERS = [
  { value: 'all', label: 'Все' },
  { value: 'with_sub', label: 'С подпиской' },
  { value: 'monthly', label: 'Купили 1 мес.' },
  { value: 'two_months', label: 'Купили 2 мес.' },
  { value: 'quarterly', label: 'Купили 3 мес.' },
  { value: 'granted', label: 'Выданные' },
  { value: 'inactive', label: 'Без подписки' },
  { value: 'unpaid', label: 'Оплата без подписки' },
  { value: 'referrals', label: 'Рефералы' },
  { value: 'trial', label: 'Пробный период' },
] as const

type SubFilter = (typeof SUB_FILTERS)[number]['value']

function readStoredFilter(): SubFilter {
  try {
    const raw = localStorage.getItem(SUB_FILTER_KEY)
    if (raw === 'active') return 'with_sub'
    if (raw && SUB_FILTERS.some(f => f.value === raw)) return raw as SubFilter
  } catch { /* private mode */ }
  return 'all'
}

const PLAN_NAMES: Record<string, string> = {
  trial: 'Пробный',
  test: 'Тест',
  three_days: '3 дня',
  monthly: 'Месяц',
  two_months: '2 месяца',
  quarterly: '3 месяца',
  half_year: 'Полгода',
  yearly: 'Год',
  unlimited: '∞',
  referral_bonus: 'Реферал',
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

function fmtDate(v: string | null | undefined): string {
  if (!v) return '—'
  return v.split('T')[0]
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  return `${Number(n).toFixed(0)} ₽`
}

export default function SubscriptionsPage({ token }: { token: string }) {
  const [users, setUsers] = useState<UserRow[]>([])
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [filter, setFilter] = useState<SubFilter>(() => readStoredFilter())
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [actionKey, setActionKey] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [testMode, setTestMode] = useState(false)
  const [testModeBusy, setTestModeBusy] = useState(false)

  const [orphans, setOrphans] = useState<Array<{ payment: PaymentRow; user: { id: string; display_id: string; email: string } }>>([])

  const [codeOpen, setCodeOpen] = useState(false)
  const [codeInput, setCodeInput] = useState('')
  const [codeBusy, setCodeBusy] = useState(false)
  const [codeResult, setCodeResult] = useState<CodeLookup | null>(null)
  const [codeError, setCodeError] = useState<string | null>(null)

  const [historyOpen, setHistoryOpen] = useState(false)
  const [history, setHistory] = useState<HistoryPayload | null>(null)
  const [historyBusy, setHistoryBusy] = useState(false)

  const headers = { Authorization: `Bearer ${token}` }
  const pageSize = 50

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search.trim()), 280)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, filter])

  const setAndStoreFilter = (value: string) => {
    const next = (SUB_FILTERS.some(f => f.value === value) ? value : 'all') as SubFilter
    setFilter(next)
    try { localStorage.setItem(SUB_FILTER_KEY, next) } catch { /* ignore */ }
  }

  const fetchTestMode = async () => {
    const res = await fetch('/api/admin/subscriptions/registration-test-mode', { headers })
    if (res.ok) {
      const data = await res.json()
      setTestMode(!!data.enabled)
    }
  }

  useEffect(() => {
    let alive = true
    const searching = debouncedSearch.length > 0
    const load = async () => {
      setLoading(true)
      setError(null)
      const params = new URLSearchParams({
        // Поиск всегда с page=1 по всей базе (сервер отдаёт все совпадения).
        page: String(searching ? 1 : page),
        page_size: searching ? '500' : String(pageSize),
        filter,
        q: debouncedSearch,
      })
      try {
        const res = await fetch(`/api/admin/subscriptions/users?${params}`, { headers })
        if (!alive) return
        if (!res.ok) {
          setError('Не удалось загрузить пользователей')
          setLoading(false)
          return
        }
        const data = await res.json()
        if (!alive) return
        setUsers(data.items || [])
        setTotal(data.total ?? 0)
        setPages(searching ? 1 : (data.pages ?? 1))
        setLoading(false)
      } catch {
        if (!alive) return
        setError('Не удалось загрузить пользователей')
        setLoading(false)
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [page, filter, debouncedSearch, token])

  const fetchUsers = async () => {
    setLoading(true)
    setError(null)
    const searching = debouncedSearch.length > 0
    const params = new URLSearchParams({
      page: String(searching ? 1 : page),
      page_size: searching ? '500' : String(pageSize),
      filter,
      q: debouncedSearch,
    })
    const res = await fetch(`/api/admin/subscriptions/users?${params}`, { headers })
    if (!res.ok) {
      setError('Не удалось загрузить пользователей')
      setLoading(false)
      return
    }
    const data = await res.json()
    setUsers(data.items || [])
    setTotal(data.total ?? 0)
    setPages(searching ? 1 : (data.pages ?? 1))
    setLoading(false)
  }

  const fetchOrphans = async () => {
    const res = await fetch('/api/admin/subscriptions/orphan-payments?limit=12', { headers })
    if (res.ok) {
      const data = await res.json()
      setOrphans(data.items || [])
    }
  }

  useEffect(() => {
    fetchTestMode()
    fetchOrphans()
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
          : `Глобальный тестовый режим выключен${n ? ` (очищено тест-подписок: ${n})` : ''}`,
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
      setSuccess(next ? `Безлимит включён для ${u.email}` : `Безлимит выключен для ${u.email}`)
      await fetchUsers()
      if (history?.user.id === u.id) await openHistory(u.id)
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
      await fetchOrphans()
      if (history?.user.id === u.id) await openHistory(u.id)
    } finally {
      setActionKey(null)
    }
  }

  const openHistory = async (userId: string) => {
    setHistoryBusy(true)
    setHistoryOpen(true)
    setError(null)
    try {
      const res = await fetch(`/api/admin/users/${userId}/subscription-history`, { headers })
      if (!res.ok) {
        setError('Не удалось загрузить историю')
        setHistory(null)
        return
      }
      setHistory(await res.json())
    } finally {
      setHistoryBusy(false)
    }
  }

  const lookupCode = async () => {
    const code = codeInput.trim()
    if (!code) return
    setCodeBusy(true)
    setCodeError(null)
    setCodeResult(null)
    try {
      const res = await fetch(`/api/admin/subscriptions/by-code/${encodeURIComponent(code)}`, { headers })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setCodeError(body.detail || 'Код не найден')
        return
      }
      setCodeResult(body)
    } finally {
      setCodeBusy(false)
    }
  }

  const activateByCode = async () => {
    const code = codeResult?.payment.support_code || codeInput.trim()
    if (!code) return
    setCodeBusy(true)
    setCodeError(null)
    try {
      const res = await fetch(`/api/admin/subscriptions/by-code/${encodeURIComponent(code)}/activate`, {
        method: 'POST',
        headers,
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setCodeError(typeof body.detail === 'string' ? body.detail : 'Не удалось подключить')
        return
      }
      setCodeResult(body)
      setSuccess(`Подписка подключена для ${body.user?.email || 'пользователя'}`)
      await fetchUsers()
      await fetchOrphans()
    } finally {
      setCodeBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Calendar className="w-5 h-5" />
            Выдача подписок
          </h1>
          <p className="text-sm text-[#666] mt-1">
            Код из письма · история оплат · выдача планов
          </p>
          <p className="text-xs text-[#555] mt-1">
            {loading
              ? '…'
              : debouncedSearch
                ? `Найдено: ${total.toLocaleString('ru-RU')}`
                : `${total.toLocaleString('ru-RU')} пользователей · стр. ${page}/${pages}`}
          </p>
        </div>
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 shrink-0">
          <button
            type="button"
            onClick={() => {
              setCodeOpen(true)
              setCodeError(null)
              setCodeResult(null)
            }}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-[#333] bg-[#111] text-sm text-[#eee] hover:border-[#555] hover:bg-[#161616] transition-colors cursor-pointer"
          >
            <KeyRound className="w-3.5 h-3.5" />
            Код оплаты
          </button>
          <button
            type="button"
            onClick={toggleTestMode}
            disabled={testModeBusy}
            className={`flex items-center justify-between gap-3 px-4 py-2 rounded-lg border text-sm transition-colors disabled:opacity-50 cursor-pointer ${
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
            className="w-full sm:w-56 shrink-0 min-w-0"
          />
          <SortSelect
            value={filter}
            onChange={setAndStoreFilter}
            options={[...SUB_FILTERS]}
            className="w-full sm:w-56 shrink-0"
            label="Фильтр подписок"
          />
        </div>
      </div>

      {orphans.length > 0 && (
        <div className="bg-amber-500/8 border border-amber-500/25 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2 text-amber-300 text-sm font-medium mb-2">
            <AlertTriangle className="w-4 h-4" />
            Оплата без подписки ({orphans.length})
          </div>
          <div className="flex flex-col gap-1.5">
            {orphans.map(o => (
              <button
                key={o.payment.id}
                type="button"
                onClick={() => {
                  setCodeOpen(true)
                  setCodeError(null)
                  setCodeResult(null)
                  const c = o.payment.support_code || ''
                  setCodeInput(c)
                }}
                className="text-left text-xs text-[#ccc] hover:text-white flex flex-wrap gap-x-3 gap-y-0.5 cursor-pointer"
              >
                <span className="font-mono text-amber-200/90">{o.payment.support_code || '—'}</span>
                <span>{o.user.email}</span>
                <span className="text-[#666]">
                  {PLAN_NAMES[o.payment.plan_type] || o.payment.plan_type} · {fmtMoney(o.payment.amount)} ·{' '}
                  {fmtDate(o.payment.completed_at)}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {testMode && (
        <div className="bg-purple-500/10 border border-purple-500/30 text-purple-300 text-sm rounded-lg px-4 py-3">
          Глобальный тестовый режим активен: все пользователи получают безлимит.
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
        <table className="w-full text-sm min-w-[860px]">
          <thead>
            <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">ID</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Текущая</th>
              <th className="text-left px-4 py-3">Оплаты</th>
              <th className="text-center px-4 py-3">Тест</th>
              <th className="px-4 py-3 text-right">Планы</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="text-center py-12 text-[#555]">
                  Загрузка...
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center py-12 text-[#555]">
                  Никого не найдено
                </td>
              </tr>
            ) : (
              users.map(u => (
                <tr
                  key={u.id}
                  className="border-b border-[#1a1a1a] hover:bg-[#151515] transition-colors cursor-pointer"
                  onClick={() => openHistory(u.id)}
                >
                  <td className="px-4 py-3 font-mono text-[#888]">{u.display_id}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>{u.email}</span>
                      {u.is_test_user && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/40">
                          Личный
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-xs ${
                        u.subscription.active || u.is_admin || (u.in_test_mode ?? u.is_test_user)
                          ? 'text-green-400'
                          : 'text-[#555]'
                      }`}
                    >
                      {subscriptionLabel(u)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-[#888]">{u.payments_completed ?? 0}</td>
                  <td className="px-4 py-3 text-center" onClick={e => e.stopPropagation()}>
                    {u.is_admin ? (
                      <span className="text-xs text-[#555]">—</span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => toggleUserTestMode(u)}
                        disabled={actionKey === `${u.id}:test`}
                        className="inline-flex items-center disabled:opacity-40 cursor-pointer"
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
                  <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
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
                              type="button"
                              onClick={() => togglePlan(u, p.type, p.label)}
                              disabled={busy}
                              title={
                                active
                                  ? `Забрать «${p.label}»`
                                  : `Выдать «${p.label}»${p.days ? ` (${p.days} дн.)` : ''}`
                              }
                              className={`px-2.5 py-1 rounded-lg text-xs border transition-colors disabled:opacity-40 cursor-pointer ${
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

      {!debouncedSearch && pages > 1 && (
        <div className="flex items-center justify-between gap-3">
          <button
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => setPage(p => Math.max(1, p - 1))}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[#2a2a2a] text-xs text-[#ccc] disabled:opacity-40 hover:border-[#444] cursor-pointer"
          >
            <ChevronLeft className="w-3.5 h-3.5" /> Назад
          </button>
          <span className="text-xs text-[#666]">
            {page} / {pages}
          </span>
          <button
            type="button"
            disabled={page >= pages || loading}
            onClick={() => setPage(p => Math.min(pages, p + 1))}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[#2a2a2a] text-xs text-[#ccc] disabled:opacity-40 hover:border-[#444] cursor-pointer"
          >
            Вперёд <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Модалка кода оплаты */}
      {codeOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70"
          onClick={() => setCodeOpen(false)}
        >
          <div
            className="w-full max-w-lg bg-[#111] border border-[#2a2a2a] rounded-xl shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-[#222]">
              <div className="flex items-center gap-2 font-semibold">
                <KeyRound className="w-4 h-4" />
                Код оплаты
              </div>
              <button
                type="button"
                onClick={() => setCodeOpen(false)}
                className="p-1 rounded-md text-[#666] hover:text-white hover:bg-[#1a1a1a] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <p className="text-xs text-[#666]">
                Код из письма после YuMoney. Покажет пользователя, оплату и можно вручную подключить подписку.
              </p>
              <div className="flex gap-2">
                <input
                  value={codeInput}
                  onChange={e => setCodeInput(e.target.value.toUpperCase())}
                  onKeyDown={e => e.key === 'Enter' && lookupCode()}
                  placeholder="SV-XXXX-XXXX"
                  className="flex-1 bg-[#0a0a0a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm font-mono tracking-wider text-white placeholder:text-[#444] focus:outline-none focus:border-[#444]"
                />
                <button
                  type="button"
                  onClick={lookupCode}
                  disabled={codeBusy || !codeInput.trim()}
                  className="px-4 py-2 rounded-lg bg-white text-black text-sm font-semibold hover:bg-[#e0e0e0] disabled:opacity-40 cursor-pointer"
                >
                  {codeBusy ? '…' : 'Найти'}
                </button>
              </div>
              {codeError && (
                <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
                  {codeError}
                </div>
              )}
              {codeResult && (
                <div className="rounded-xl border border-[#2a2a2a] bg-[#0a0a0a] p-4 space-y-3">
                  <div className="flex flex-wrap justify-between gap-2 text-sm">
                    <div>
                      <div className="text-[#666] text-xs mb-0.5">Пользователь</div>
                      <div>{codeResult.user.email}</div>
                      <div className="font-mono text-xs text-[#666]">{codeResult.user.display_id}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-[#666] text-xs mb-0.5">Подписка сейчас</div>
                      <div
                        className={
                          codeResult.user.subscription.active ? 'text-green-400' : 'text-amber-300'
                        }
                      >
                        {subscriptionLabel(codeResult.user)}
                      </div>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <div className="text-[#555]">План оплаты</div>
                      <div>{PLAN_NAMES[codeResult.payment.plan_type] || codeResult.payment.plan_type}</div>
                    </div>
                    <div>
                      <div className="text-[#555]">Сумма</div>
                      <div>{fmtMoney(codeResult.payment.paid_amount ?? codeResult.payment.amount)}</div>
                    </div>
                    <div>
                      <div className="text-[#555]">Оплачено</div>
                      <div>{fmtDate(codeResult.payment.completed_at)}</div>
                    </div>
                    <div>
                      <div className="text-[#555]">Выдача</div>
                      <div
                        className={
                          codeResult.payment.subscription_applied ? 'text-green-400' : 'text-amber-300'
                        }
                      >
                        {codeResult.payment.subscription_applied
                          ? codeResult.payment.manual_activated_at
                            ? 'Вручную'
                            : 'Авто'
                          : 'Не подключена'}
                      </div>
                    </div>
                  </div>
                  {codeResult.needs_activation && (
                    <button
                      type="button"
                      onClick={activateByCode}
                      disabled={codeBusy}
                      className="w-full py-2.5 rounded-lg bg-green-500/20 border border-green-500/50 text-green-300 text-sm font-semibold hover:bg-green-500/30 disabled:opacity-40 cursor-pointer"
                    >
                      Подключить подписку вручную
                    </button>
                  )}
                  {!codeResult.needs_activation && codeResult.payment.subscription_applied && (
                    <div className="text-center text-xs text-green-400/90 py-1">Подписка уже привязана к оплате</div>
                  )}
                  <button
                    type="button"
                    onClick={() => openHistory(codeResult.user.id)}
                    className="w-full py-2 rounded-lg border border-[#2a2a2a] text-xs text-[#aaa] hover:text-white hover:border-[#444] cursor-pointer"
                  >
                    Открыть историю пользователя
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Боковая панель истории */}
      {historyOpen && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <button
            type="button"
            aria-label="Закрыть"
            className="absolute inset-0 bg-black/60 cursor-pointer"
            onClick={() => setHistoryOpen(false)}
          />
          <aside className="relative w-full max-w-md h-full bg-[#0d0d0d] border-l border-[#222] shadow-2xl overflow-y-auto">
            <div className="sticky top-0 z-10 flex items-center justify-between px-5 py-4 border-b border-[#222] bg-[#0d0d0d]/backdrop-blur">
              <div>
                <div className="font-semibold text-sm">История подписки</div>
                <div className="text-xs text-[#666] mt-0.5 truncate max-w-[240px]">
                  {history?.user.email || (historyBusy ? '…' : '')}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setHistoryOpen(false)}
                className="p-1.5 rounded-md text-[#666] hover:text-white hover:bg-[#1a1a1a] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-5 space-y-6">
              {historyBusy && !history ? (
                <div className="text-center text-[#555] py-10 text-sm">Загрузка…</div>
              ) : history ? (
                <>
                  <div className="rounded-xl border border-[#222] bg-[#111] p-4">
                    <div className="text-xs text-[#555] mb-1">Сейчас</div>
                    <div
                      className={`text-sm ${
                        history.user.subscription.active ? 'text-green-400' : 'text-[#888]'
                      }`}
                    >
                      {subscriptionLabel(history.user)}
                    </div>
                    <div className="mt-2 font-mono text-xs text-[#555]">{history.user.display_id}</div>
                  </div>

                  <section>
                    <h3 className="text-xs uppercase tracking-wider text-[#555] mb-3">Оплаты</h3>
                    {history.payments.length === 0 ? (
                      <p className="text-xs text-[#555]">Нет оплат</p>
                    ) : (
                      <ul className="space-y-2">
                        {history.payments.map(p => (
                          <li
                            key={p.id}
                            className="rounded-lg border border-[#1f1f1f] bg-[#111] px-3 py-2.5 text-xs"
                          >
                            <div className="flex justify-between gap-2">
                              <span className="text-[#ddd]">
                                {PLAN_NAMES[p.plan_type] || p.plan_type}
                              </span>
                              <span className="text-[#aaa]">{fmtMoney(p.paid_amount ?? p.amount)}</span>
                            </div>
                            <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5 text-[#666]">
                              <span>{p.status}</span>
                              <span>{fmtDate(p.completed_at || p.created_at)}</span>
                              {p.support_code && (
                                <button
                                  type="button"
                                  className="font-mono text-amber-200/80 hover:text-amber-100 cursor-pointer"
                                  onClick={() => {
                                    setCodeOpen(true)
                                    setCodeInput(p.support_code || '')
                                    setCodeResult(null)
                                  }}
                                >
                                  {p.support_code}
                                </button>
                              )}
                              <span
                                className={
                                  p.subscription_applied ? 'text-green-500/80' : 'text-amber-400/80'
                                }
                              >
                                {p.subscription_applied ? 'выдано' : 'без подписки'}
                              </span>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section>
                    <h3 className="text-xs uppercase tracking-wider text-[#555] mb-3">Периоды</h3>
                    {history.subscriptions.length === 0 ? (
                      <p className="text-xs text-[#555]">Нет записей</p>
                    ) : (
                      <ul className="space-y-2">
                        {history.subscriptions.map(s => (
                          <li
                            key={s.id}
                            className="rounded-lg border border-[#1f1f1f] bg-[#111] px-3 py-2.5 text-xs"
                          >
                            <div className="flex justify-between gap-2">
                              <span className="text-[#ddd]">
                                {PLAN_NAMES[s.plan_type] || s.plan_type}
                              </span>
                              <span
                                className={
                                  s.is_active_now ? 'text-green-400' : 'text-[#666]'
                                }
                              >
                                {s.status}
                              </span>
                            </div>
                            <div className="mt-1.5 text-[#666]">
                              {fmtDate(s.started_at)} → {fmtDate(s.expires_at)}
                              {s.amount_paid > 0 ? ` · ${fmtMoney(s.amount_paid)}` : ''}
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </>
              ) : null}
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
