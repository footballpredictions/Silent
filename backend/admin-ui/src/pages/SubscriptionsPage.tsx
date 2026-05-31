import { useEffect, useState } from 'react'
import { Search, Calendar } from 'lucide-react'

interface UserRow {
  id: string
  display_id: string
  email: string
  is_verified: boolean
  is_active: boolean
  is_admin?: boolean
  subscription: { active: boolean; plan: string | null; expires_at: string | null }
}

const PLANS = [
  { type: 'three_days', label: '3 дня',    days: 3 },
  { type: 'monthly',    label: 'Месяц',    days: 30 },
  { type: 'quarterly',  label: '3 месяца', days: 90 },
  { type: 'yearly',     label: 'Год',      days: 365 },
  { type: 'unlimited',  label: '∞',        days: null },
] as const

const PLAN_NAMES: Record<string, string> = {
  trial:      'Пробный',
  three_days: '3 дня',
  monthly:    'Месяц',
  quarterly:  '3 месяца',
  yearly:     'Год',
  unlimited:  '∞',
}

function subscriptionLabel(u: UserRow): string {
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

  const headers = { Authorization: `Bearer ${token}` }

  const fetchUsers = async () => {
    setLoading(true)
    setError(null)
    const res = await fetch('/api/admin/users?limit=200', { headers })
    if (!res.ok) {
      setError('Не удалось загрузить пользователей')
      setLoading(false)
      return
    }
    setUsers(await res.json())
    setLoading(false)
  }

  useEffect(() => { fetchUsers() }, [])

  const isPlanActive = (u: UserRow, planType: string) =>
    u.subscription.active && u.subscription.plan === planType

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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Calendar className="w-5 h-5" />
            Выдача подписок
          </h1>
          <p className="text-sm text-[#666] mt-1">Нажмите план чтобы выдать, повторно — чтобы забрать</p>
        </div>
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#555]" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск..."
            className="bg-[#111] border border-[#222] rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#444]"
          />
        </div>
      </div>

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

      <div className="bg-[#111] border border-[#222] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">ID</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Текущая подписка</th>
              <th className="text-left px-4 py-3">Статус</th>
              <th className="px-4 py-3 text-right">Планы</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="text-center py-12 text-[#555]">Загрузка...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={5} className="text-center py-12 text-[#555]">Нет пользователей</td></tr>
            ) : (
              filtered.map(u => (
                <tr key={u.id} className="border-b border-[#1a1a1a] hover:bg-[#151515] transition-colors">
                  <td className="px-4 py-3 font-mono text-[#888]">{u.display_id}</td>
                  <td className="px-4 py-3">{u.email}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs ${u.subscription.active || u.is_admin ? 'text-green-400' : 'text-[#555]'}`}>
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
                  <td className="px-4 py-3">
                    {u.is_admin ? (
                      <div className="text-right text-xs font-semibold text-amber-400/90">Админ</div>
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
