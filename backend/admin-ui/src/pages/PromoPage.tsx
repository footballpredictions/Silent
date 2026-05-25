import { useState, useEffect } from 'react'
import { Plus } from 'lucide-react'

export default function PromoPage({ token }: { token: string }) {
  const [promos, setPromos] = useState<any[]>([])
  const [form, setForm] = useState({ code: '', discount_percent: 0, extra_days: 0, max_uses: 1, expires_at: '' })
  const [creating, setCreating] = useState(false)

  const fetchPromos = async () => {
    const res = await fetch('/api/admin/promo', { headers: { Authorization: `Bearer ${token}` } })
    setPromos(await res.json())
  }

  useEffect(() => { fetchPromos() }, [])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    await fetch('/api/admin/promo', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, expires_at: form.expires_at || null }),
    })
    setForm({ code: '', discount_percent: 0, extra_days: 0, max_uses: 1, expires_at: '' })
    fetchPromos()
    setCreating(false)
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-xl font-bold">Промокоды</h1>

      <div className="bg-[#111] border border-[#222] rounded-xl p-6">
        <h2 className="font-semibold mb-4 flex items-center gap-2"><Plus className="w-4 h-4" /> Создать промокод</h2>
        <form onSubmit={create} className="grid grid-cols-2 gap-3">
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

      <div className="bg-[#111] border border-[#222] rounded-xl overflow-hidden">
        <table className="w-full text-sm">
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
                <td className="px-4 py-3 text-[#888]">{p.expires_at ? p.expires_at.split('T')[0] : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
