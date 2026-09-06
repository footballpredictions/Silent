import { useEffect, useMemo, useState } from 'react'
import { Ban, CheckCircle, ShieldCheck, Trash2 } from 'lucide-react'
import SearchInput from '../components/SearchInput'
import SortSelect from '../components/SortSelect'

interface UserRow {
  id: string; display_id: string; email: string; is_verified: boolean; is_active: boolean
  is_admin?: boolean
  is_test_user?: boolean
  test_mode_excluded?: boolean
  in_test_mode?: boolean
  created_at: string; bootstrap_hash: string | null; server_hashes: number
  subscription: { active: boolean; plan: string | null; expires_at: string | null }
  devices_count: number
  is_online?: boolean
  online_devices?: number
  acquisition?: 'referral' | 'promo' | 'organic' | string
  pending_promo_code?: string | null
  referral_code?: string | null
}

const USERS_SORT_KEY = 'admin.users.sort'

const USERS_SORTS = [
  { value: 'online', label: 'Онлайн сначала' },
  { value: 'unverified', label: 'Неверифицированные' },
  { value: 'email_az', label: 'По алфавиту А→Я' },
  { value: 'email_za', label: 'По алфавиту Я→А' },
  { value: 'registered_new', label: 'Новые сначала' },
  { value: 'registered_old', label: 'Старые сначала' },
  { value: 'subscription', label: 'Подписка сначала' },
] as const

type UsersSort = (typeof USERS_SORTS)[number]['value']

function parseTs(iso?: string | null): number {
  if (!iso) return 0
  let s = String(iso).trim()
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) {
    s = s.replace(' ', 'T')
    if (!s.endsWith('Z')) s += 'Z'
  }
  const t = new Date(s).getTime()
  return Number.isNaN(t) ? 0 : t
}

function formatRegDate(iso?: string | null): string {
  const t = parseTs(iso)
  if (!t) return '—'
  return new Date(t).toLocaleDateString('ru-RU', {
    timeZone: 'Europe/Moscow',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

function subscriptionLabel(u: UserRow): string {
  const inTest = u.in_test_mode ?? u.is_test_user
  if (inTest || u.subscription.plan === 'test') return 'Тест · безлимит'
  if (u.is_admin || u.subscription.plan === 'unlimited') return '∞'
  if (!u.subscription.active) return 'Нет'
  const plan = u.subscription.plan === 'trial' ? 'Пробный' : u.subscription.plan
  const until = u.subscription.expires_at?.split('T')[0]
  return until ? `${plan} · до ${until}` : plan || 'Активна'
}

function devicesLabel(u: UserRow): string {
  return u.is_admin ? `${u.devices_count}/∞` : `${u.devices_count}/3`
}

export default function UsersPage({ token }: { token: string }) {
  const [users, setUsers] = useState<UserRow[]>([])
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<UsersSort>(() => {
    try {
      const raw = localStorage.getItem(USERS_SORT_KEY)
      if (raw && USERS_SORTS.some(s => s.value === raw)) return raw as UsersSort
    } catch { /* ignore */ }
    return 'registered_new'
  })
  const [loading, setLoading] = useState(true)
  const [actionId, setActionId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const headers = { Authorization: `Bearer ${token}` }

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

  useEffect(() => { fetchUsers() }, [])

  const apiAction = async (id: string, path: string, method: string) => {
    setActionId(id)
    setError(null)
    try {
      const res = await fetch(`/api/admin/users/${id}${path}`, { method, headers })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setError(body.detail || 'Ошибка операции')
        return
      }
      await fetchUsers()
    } finally {
      setActionId(null)
    }
  }

  const toggleBan = (id: string) => apiAction(id, '/ban', 'POST')
  const verifyUser = (id: string) => apiAction(id, '/verify', 'POST')

  const deleteUser = async (u: UserRow) => {
    if (!confirm(`Удалить пользователя ${u.email}?\n\nБудут удалены устройства, подписки, платежи и VK-хеши.`)) {
      return
    }
    await apiAction(u.id, '', 'DELETE')
  }

  const setAndStoreSort = (value: string) => {
    const next = (USERS_SORTS.some(s => s.value === value) ? value : 'registered_new') as UsersSort
    setSort(next)
    try { localStorage.setItem(USERS_SORT_KEY, next) } catch { /* ignore */ }
  }

  const filtered = useMemo(() => {
    const q = search.toLowerCase()
    const list = users.filter(u =>
      !u.email.includes('bootstrap') && (
        u.email.toLowerCase().includes(q) ||
        u.display_id.toLowerCase().includes(q)
      )
    )
    const subRank = (u: UserRow) => {
      if (u.is_admin || u.subscription.plan === 'unlimited') return 3
      if (u.in_test_mode ?? u.is_test_user) return 2
      if (u.subscription.active) return 1
      return 0
    }
    list.sort((a, b) => {
      const byAdmin = Number(Boolean(b.is_admin)) - Number(Boolean(a.is_admin))
      if (byAdmin) return byAdmin
      switch (sort) {
        case 'online': {
          const byOnline = Number(Boolean(b.is_online)) - Number(Boolean(a.is_online))
          if (byOnline) return byOnline
          return parseTs(b.created_at) - parseTs(a.created_at)
        }
        case 'unverified': {
          const byUnverified = Number(Boolean(a.is_verified)) - Number(Boolean(b.is_verified))
          if (byUnverified) return byUnverified
          return parseTs(b.created_at) - parseTs(a.created_at)
        }
        case 'email_az':
          return a.email.localeCompare(b.email, 'ru', { sensitivity: 'base' })
        case 'email_za':
          return b.email.localeCompare(a.email, 'ru', { sensitivity: 'base' })
        case 'registered_new':
          return parseTs(b.created_at) - parseTs(a.created_at)
        case 'registered_old':
          return parseTs(a.created_at) - parseTs(b.created_at)
        case 'subscription': {
          const bySub = subRank(b) - subRank(a)
          if (bySub) return bySub
          return parseTs(b.created_at) - parseTs(a.created_at)
        }
        default:
          return 0
      }
    })
    return list
  }, [users, search, sort])

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">Пользователи</h1>
          <p className="text-xs text-[#666] mt-1">{loading ? '…' : `${filtered.length} из ${users.length}`}</p>
        </div>
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:w-auto">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Поиск по email или ID…"
            className="w-full sm:w-56"
          />
          <SortSelect
            value={sort}
            onChange={setAndStoreSort}
            options={[...USERS_SORTS]}
            className="w-full sm:w-48"
            label="Сортировка пользователей"
          />
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      <div className="bg-[#111] border border-[#222] rounded-xl overflow-x-auto">
        <table className="w-full text-sm min-w-[780px]">
          <thead>
            <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">ID</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Рег.</th>
              <th className="text-left px-4 py-3">Bootstrap</th>
              <th className="text-left px-4 py-3">Сервер</th>
              <th className="text-left px-4 py-3">Подписка</th>
              <th className="text-left px-4 py-3">Устройств</th>
              <th className="text-left px-4 py-3">Статус</th>
              <th className="px-4 py-3 text-right">Действия</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="text-center py-12 text-[#555]">Загрузка...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={9} className="text-center py-12 text-[#555]">Нет пользователей</td></tr>
            ) : (
              filtered.map(u => (
                <tr key={u.id} className="border-b border-[#1a1a1a] hover:bg-[#151515] transition-colors">
                  <td className="px-4 py-3 font-mono text-[#888]">{u.display_id}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>{u.email}</span>
                      {u.is_online && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-green-500/15 text-green-400 border border-green-500/30">
                          Онлайн
                        </span>
                      )}
                      {(u.in_test_mode ?? u.is_test_user) && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/40">
                          Тест
                        </span>
                      )}
                      {u.acquisition === 'referral' && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-sky-500/15 text-sky-300 border border-sky-500/30">
                          Реф
                        </span>
                      )}
                      {u.acquisition === 'promo' && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-300 border border-violet-500/30" title={u.pending_promo_code || ''}>
                          Промо
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-[#888] whitespace-nowrap">{formatRegDate(u.created_at)}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[#888]">{u.bootstrap_hash || '—'}</td>
                  <td className="px-4 py-3 text-center">{u.server_hashes ?? 0}/3</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs ${u.subscription.active || u.is_admin || (u.in_test_mode ?? u.is_test_user) ? 'text-green-400' : 'text-[#555]'}`}>
                      {subscriptionLabel(u)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">{devicesLabel(u)}</td>
                  <td className="px-4 py-3">
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <div className={`w-1.5 h-1.5 rounded-full ${u.is_active ? 'bg-green-400' : 'bg-red-400'}`} />
                        <span className="text-xs text-[#888]">{u.is_active ? 'Активен' : 'Заблокирован'}</span>
                      </div>
                      <span className={`text-xs ${u.is_verified ? 'text-green-400/80' : 'text-amber-400/80'}`}>
                        {u.is_verified ? 'Верифицирован' : 'Не верифицирован'}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {u.is_admin ? (
                      <div className="text-right text-xs font-semibold text-amber-400/90 tracking-wide">
                        Админ
                      </div>
                    ) : (
                      <div className="flex items-center justify-end gap-1">
                        {!u.is_verified && (
                          <button
                            onClick={() => verifyUser(u.id)}
                            disabled={actionId === u.id}
                            className="p-1.5 rounded-lg transition-colors hover:bg-blue-500/20 text-[#555] hover:text-blue-400 disabled:opacity-40"
                            title="Верифицировать без email"
                          >
                            <ShieldCheck className="w-3.5 h-3.5" />
                          </button>
                        )}
                        <button
                          onClick={() => toggleBan(u.id)}
                          disabled={actionId === u.id}
                          className={`p-1.5 rounded-lg transition-colors disabled:opacity-40 ${u.is_active ? 'hover:bg-red-500/20 text-[#555] hover:text-red-400' : 'hover:bg-green-500/20 text-[#555] hover:text-green-400'}`}
                          title={u.is_active ? 'Заблокировать' : 'Разблокировать'}
                        >
                          {u.is_active ? <Ban className="w-3.5 h-3.5" /> : <CheckCircle className="w-3.5 h-3.5" />}
                        </button>
                        <button
                          onClick={() => deleteUser(u)}
                          disabled={actionId === u.id}
                          className="p-1.5 rounded-lg transition-colors hover:bg-red-500/20 text-[#555] hover:text-red-400 disabled:opacity-40"
                          title="Удалить пользователя"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
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
