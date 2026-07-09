import { useState, useEffect, useCallback } from 'react'
import { Plus, Gift, Users, Tag } from 'lucide-react'

type Tab = 'promo' | 'stats'

export default function BonusesPage({ token }: { token: string }) {
  const [tab, setTab] = useState<Tab>('promo')
  const [promos, setPromos] = useState<any[]>([])
  const [stats, setStats] = useState<any>(null)
  const [form, setForm] = useState({ code: '', discount_percent: 0, extra_days: 0, max_uses: 1, expires_at: '' })
  const [creating, setCreating] = useState(false)
  const [loadingStats, setLoadingStats] = useState(false)

  const fetchPromos = useCallback(async () => {
    const res = await fetch('/api/admin/promo', { headers: { Authorization: `Bearer ${token}` } })
    if (res.ok) setPromos(await res.json())
  }, [token])

  const fetchStats = useCallback(async () => {
    setLoadingStats(true)
    try {
      const res = await fetch('/api/admin/bonuses/stats', { headers: { Authorization: `Bearer ${token}` } })
      if (res.ok) setStats(await res.json())
    } finally {
      setLoadingStats(false)
    }
  }, [token])

  useEffect(() => {
    fetchPromos()
  }, [fetchPromos])

  useEffect(() => {
    if (tab === 'stats') fetchStats()
  }, [tab, fetchStats])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    await fetch('/api/admin/promo', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, expires_at: form.expires_at || null }),
    })
    setForm({ code: '', discount_percent: 0, extra_days: 0, max_uses: 1, expires_at: '' })
    await fetchPromos()
    setCreating(false)
  }

  const s = stats?.summary

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Gift className="w-5 h-5" /> Бонусы
        </h1>
        <p className="text-sm text-[#666] mt-1">
          Промокоды и реферальная программа. Кто пришёл по рефу / с промо — в статистике ниже.
        </p>
      </div>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setTab('promo')}
          className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
            tab === 'promo' ? 'bg-white text-black border-white' : 'bg-[#111] text-[#888] border-[#333] hover:text-white'
          }`}
        >
          <span className="inline-flex items-center gap-1.5"><Tag className="w-3.5 h-3.5" /> Промокоды</span>
        </button>
        <button
          type="button"
          onClick={() => setTab('stats')}
          className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
            tab === 'stats' ? 'bg-white text-black border-white' : 'bg-[#111] text-[#888] border-[#333] hover:text-white'
          }`}
        >
          <span className="inline-flex items-center gap-1.5"><Users className="w-3.5 h-3.5" /> Рефералы и статистика</span>
        </button>
      </div>

      {tab === 'promo' && (
        <>
          <div className="bg-[#111] border border-[#222] rounded-xl p-6">
            <h2 className="font-semibold mb-4 flex items-center gap-2"><Plus className="w-4 h-4" /> Создать промокод</h2>
            <form onSubmit={create} className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="text-xs text-[#666] mb-1 block">Код</label>
                <input value={form.code} onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })}
                  required placeholder="WELCOME20"
                  className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-[#444]" />
              </div>
              <div>
                <label className="text-xs text-[#666] mb-1 block">Скидка %</label>
                <input type="number" min={0} max={100} value={form.discount_percent}
                  onChange={e => setForm({ ...form, discount_percent: +e.target.value })}
                  className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-[#444]" />
              </div>
              <div>
                <label className="text-xs text-[#666] mb-1 block">Бонус дней</label>
                <input type="number" min={0} value={form.extra_days}
                  onChange={e => setForm({ ...form, extra_days: +e.target.value })}
                  className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-[#444]" />
              </div>
              <div>
                <label className="text-xs text-[#666] mb-1 block">Использований</label>
                <input type="number" min={1} value={form.max_uses}
                  onChange={e => setForm({ ...form, max_uses: +e.target.value })}
                  className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-[#444]" />
              </div>
              <div>
                <label className="text-xs text-[#666] mb-1 block">Истекает (опционально)</label>
                <input type="date" value={form.expires_at}
                  onChange={e => setForm({ ...form, expires_at: e.target.value })}
                  className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-[#444]" />
              </div>
              <div className="col-span-2">
                <button type="submit" disabled={creating}
                  className="bg-white text-black px-5 py-2 rounded-lg text-sm font-semibold hover:bg-[#e0e0e0] disabled:opacity-50 transition-colors">
                  {creating ? 'Создаём...' : 'Создать промокод'}
                </button>
              </div>
            </form>
          </div>

          <div className="bg-[#111] border border-[#222] rounded-xl overflow-x-auto">
            <table className="w-full text-sm min-w-[480px]">
              <thead>
                <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Код</th>
                  <th className="text-left px-4 py-3">Скидка</th>
                  <th className="text-left px-4 py-3">Бонус дней</th>
                  <th className="text-left px-4 py-3">Использован</th>
                  <th className="text-left px-4 py-3">Истекает</th>
                </tr>
              </thead>
              <tbody>
                {promos.map(p => (
                  <tr key={p.id} className="border-b border-[#1a1a1a]">
                    <td className="px-4 py-3 font-mono font-bold">{p.code}</td>
                    <td className="px-4 py-3">{p.discount_percent}%</td>
                    <td className="px-4 py-3">+{p.extra_days} дн.</td>
                    <td className="px-4 py-3 text-[#888]">{p.use_count} / {p.max_uses}</td>
                    <td className="px-4 py-3 text-[#888]">{p.expires_at ? String(p.expires_at).split('T')[0] : '—'}</td>
                  </tr>
                ))}
                {!promos.length && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-[#555]">Промокодов пока нет</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === 'stats' && (
        <div className="space-y-6">
          {loadingStats && !stats && <p className="text-sm text-[#666]">Загрузка…</p>}
          {s && (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {[
                ['По рефералке', s.users_from_referral],
                ['Ожидают оплату', s.referral_pending],
                ['Награждено пар', s.referral_rewarded],
                ['С промо (pending)', s.users_with_pending_promo],
                [`Лимит / +дней`, `${s.monthly_reward_limit} / +${s.bonus_days}`],
              ].map(([label, val]) => (
                <div key={String(label)} className="bg-[#111] border border-[#222] rounded-xl p-4">
                  <div className="text-[11px] text-[#666] uppercase tracking-wide">{label}</div>
                  <div className="text-xl font-bold mt-1">{val}</div>
                </div>
              ))}
            </div>
          )}

          <div className="bg-[#111] border border-[#222] rounded-xl overflow-x-auto">
            <div className="px-4 py-3 border-b border-[#222] font-semibold text-sm">Топ пригласивших</div>
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Пользователь</th>
                  <th className="text-left px-4 py-3">Код</th>
                  <th className="text-left px-4 py-3">Приглашено</th>
                  <th className="text-left px-4 py-3">Награждено</th>
                  <th className="text-left px-4 py-3">Ожидают</th>
                </tr>
              </thead>
              <tbody>
                {(stats?.top_inviters || []).map((u: any) => (
                  <tr key={u.user_id} className="border-b border-[#1a1a1a]">
                    <td className="px-4 py-3">
                      <div className="font-medium">{u.email}</div>
                      <div className="text-[11px] text-[#555]">{u.display_id}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{u.referral_code || '—'}</td>
                    <td className="px-4 py-3">{u.invited_count}</td>
                    <td className="px-4 py-3 text-emerald-400">{u.rewarded_count}</td>
                    <td className="px-4 py-3 text-amber-400/90">{u.pending_count}</td>
                  </tr>
                ))}
                {!stats?.top_inviters?.length && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-[#555]">Пока нет награждённых рефералов</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="bg-[#111] border border-[#222] rounded-xl overflow-x-auto">
            <div className="px-4 py-3 border-b border-[#222] font-semibold text-sm">Последние реферальные пары</div>
            <table className="w-full text-sm min-w-[640px]">
              <thead>
                <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Источник</th>
                  <th className="text-left px-4 py-3">Пригласивший</th>
                  <th className="text-left px-4 py-3">Приглашённый</th>
                  <th className="text-left px-4 py-3">Статус</th>
                  <th className="text-left px-4 py-3">Дата</th>
                </tr>
              </thead>
              <tbody>
                {(stats?.recent_referrals || []).map((r: any) => (
                  <tr key={r.id} className="border-b border-[#1a1a1a]">
                    <td className="px-4 py-3">
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-300">реферал</span>
                    </td>
                    <td className="px-4 py-3">
                      <div>{r.inviter_email}</div>
                      <div className="text-[11px] text-[#555] font-mono">{r.inviter_code}</div>
                    </td>
                    <td className="px-4 py-3">{r.invitee_email}</td>
                    <td className="px-4 py-3">
                      {r.status === 'rewarded' ? (
                        <span className="text-emerald-400">награждено</span>
                      ) : r.status === 'pending' ? (
                        <span className="text-amber-400">ждёт оплату</span>
                      ) : (
                        <span className="text-[#888]">{r.status}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-[#888] text-xs">
                      {r.created_at ? String(r.created_at).replace('T', ' ').slice(0, 16) : '—'}
                    </td>
                  </tr>
                ))}
                {!stats?.recent_referrals?.length && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-[#555]">Реферальных пар пока нет</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="bg-[#111] border border-[#222] rounded-xl overflow-x-auto">
            <div className="px-4 py-3 border-b border-[#222] font-semibold text-sm">
              Регистрации с промокодом (ещё не применён при оплате)
            </div>
            <table className="w-full text-sm min-w-[480px]">
              <thead>
                <tr className="border-b border-[#222] text-[#555] text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Источник</th>
                  <th className="text-left px-4 py-3">Пользователь</th>
                  <th className="text-left px-4 py-3">Промокод</th>
                  <th className="text-left px-4 py-3">Дата</th>
                </tr>
              </thead>
              <tbody>
                {(stats?.pending_promo_registrations || []).map((u: any) => (
                  <tr key={u.user_id} className="border-b border-[#1a1a1a]">
                    <td className="px-4 py-3">
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-300">промо</span>
                    </td>
                    <td className="px-4 py-3">
                      <div>{u.email}</div>
                      <div className="text-[11px] text-[#555]">{u.display_id}</div>
                    </td>
                    <td className="px-4 py-3 font-mono font-bold">{u.pending_promo_code}</td>
                    <td className="px-4 py-3 text-[#888] text-xs">
                      {u.created_at ? String(u.created_at).replace('T', ' ').slice(0, 16) : '—'}
                    </td>
                  </tr>
                ))}
                {!stats?.pending_promo_registrations?.length && (
                  <tr><td colSpan={4} className="px-4 py-8 text-center text-[#555]">Нет регистраций с непромотанным промо</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
