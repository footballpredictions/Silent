import { useEffect, useState } from 'react'
import { Search, Ban, CheckCircle, ShieldCheck, Trash2 } from 'lucide-react'

interface UserRow {
  id: string; display_id: string; email: string; is_verified: boolean; is_active: boolean
  is_admin?: boolean
  is_test_user?: boolean
  test_mode_excluded?: boolean
  in_test_mode?: boolean
  created_at: string; bootstrap_hash: string | null; server_hashes: number
  subscription: { active: boolean; plan: string | null; expires_at: string | null }
  devices_count: number
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

export default function UsersPage({ token }: { token: string }) {
  const [users, setUsers] = useState<UserRow[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionId, setActionId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const headers = { Authorization: `Bearer ${token}` }

  const fetchUsers = async () => {
    setLoading(true)
    setError(null)
    const res = await fetch('/api/admin/users?limit=100', { headers })
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

  const filtered = users.filter(u =>
    !u.email.includes('bootstrap') && (
      u.email.toLowerCase().includes(search.toLowerCase()) ||
      u.display_id.toLowerCase().includes(search.toLowerCase())
    )
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <h1 className="text-xl font-bold">Пользователи</h1>
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#555]" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск..."
            className="w-full sm:w-auto bg-[#111] border border-[#222] rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder-[#555] focus:outline-none focus:border-[#444]"
          />
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      <div className="bg-[#111] border border-[#222] rounded-xl overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead>
            <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">ID</th>
              <th className="text-left px-4 py-3">Email</th>
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
              <tr><td colSpan={8} className="text-center py-12 text-[#555]">Загрузка...</td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-12 text-[#555]">Нет пользователей</td></tr>
            ) : (
              filtered.map(u => (
                <tr key={u.id} className="border-b border-[#1a1a1a] hover:bg-[#151515] transition-colors">
                  <td className="px-4 py-3 font-mono text-[#888]">{u.display_id}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>{u.email}</span>
                      {(u.in_test_mode ?? u.is_test_user) && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/40">
                          Тест
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[#888]">{u.bootstrap_hash || '—'}</td>
                  <td className="px-4 py-3 text-center">{u.server_hashes ?? 0}/3</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs ${u.subscription.active || u.is_admin || (u.in_test_mode ?? u.is_test_user) ? 'text-green-400' : 'text-[#555]'}`}>
                      {subscriptionLabel(u)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">{u.devices_count}/3</td>
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
