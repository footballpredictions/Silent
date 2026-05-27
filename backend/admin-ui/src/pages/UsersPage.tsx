import { useEffect, useState } from 'react'
import { Search, Ban, CheckCircle } from 'lucide-react'

interface UserRow {
  id: string; display_id: string; email: string; is_verified: boolean; is_active: boolean
  created_at: string; bootstrap_hash: string | null; server_hashes: number
  subscription: { active: boolean; plan: string | null; expires_at: string | null }
  devices_count: number
}

export default function UsersPage({ token }: { token: string }) {
  const [users, setUsers] = useState<UserRow[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

  const fetchUsers = async () => {
    setLoading(true)
    const res = await fetch('/api/admin/users?limit=100', {
      headers: { Authorization: `Bearer ${token}` },
    })
    setUsers(await res.json())
    setLoading(false)
  }

  useEffect(() => { fetchUsers() }, [])

  const toggleBan = async (id: string) => {
    await fetch(`/api/admin/users/${id}/ban`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    fetchUsers()
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
        <h1 className="text-xl font-bold">Пользователи</h1>
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

      <div className="bg-[#111] border border-[#222] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
              <th className="text-left px-4 py-3">ID</th>
              <th className="text-left px-4 py-3">Email</th>
              <th className="text-left px-4 py-3">Bootstrap</th>
              <th className="text-left px-4 py-3">Сервер</th>
              <th className="text-left px-4 py-3">Подписка</th>
              <th className="text-left px-4 py-3">Устройств</th>
              <th className="text-left px-4 py-3">Статус</th>
              <th className="px-4 py-3" />
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
                  <td className="px-4 py-3">{u.email}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[#888]">{u.bootstrap_hash || '—'}</td>
                  <td className="px-4 py-3 text-center">{u.server_hashes ?? 0}/3</td>
                  <td className="px-4 py-3">
                    {u.subscription.active ? (
                      <span className="text-green-400 text-xs">
                        {u.subscription.plan} · до {u.subscription.expires_at?.split('T')[0]}
                      </span>
                    ) : (
                      <span className="text-[#555] text-xs">Нет</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-center">{u.devices_count}/3</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className={`w-1.5 h-1.5 rounded-full ${u.is_active ? 'bg-green-400' : 'bg-red-400'}`} />
                      <span className="text-xs text-[#888]">{u.is_verified ? 'Верифицирован' : 'Не верифицирован'}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => toggleBan(u.id)}
                      className={`p-1.5 rounded-lg transition-colors ${u.is_active ? 'hover:bg-red-500/20 text-[#555] hover:text-red-400' : 'hover:bg-green-500/20 text-[#555] hover:text-green-400'}`}
                      title={u.is_active ? 'Заблокировать' : 'Разблокировать'}
                    >
                      {u.is_active ? <Ban className="w-3.5 h-3.5" /> : <CheckCircle className="w-3.5 h-3.5" />}
                    </button>
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
