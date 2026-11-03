import { useState, useEffect, useCallback, useRef } from 'react'
import { Plus, Gift, Users, Tag, Trash2 } from 'lucide-react'

type Tab = 'promo' | 'stats'
type PromoCounts = { users_count: number; paid_users_count: number; subscribed_users_count: number; paid_active_users_count: number }
type PromoUser = {
  user_id: string; code: string; email: string; display_id: string; created_at: string; last_seen_at: string | null
  has_paid: boolean; paid_count: number; paid_total: number; last_paid_at: string | null
  has_active_subscription: boolean; active_until: string | null; paid_active_7d: boolean; vpn_online: boolean
}
type PromoUsers = { items: PromoUser[]; total: number; offset: number; limit: number; summary: PromoCounts }
const dateTime = (value: string | null) => value ? new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'

export default function BonusesPage({ token }: { token: string }) {
  const [tab, setTab] = useState<Tab>('promo')
  const [promos, setPromos] = useState<any[]>([])
  const [stats, setStats] = useState<any>(null)
  const [form, setForm] = useState({ code: '', discount_percent: 0, extra_days: 0, max_uses: 1, expires_at: '' })
  const [creating, setCreating] = useState(false)
  const [loadingStats, setLoadingStats] = useState(false)
  const [promoToDelete, setPromoToDelete] = useState<{ id: string; code: string } | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const deleteDialog = useRef<HTMLDialogElement>(null)
  const [statsError, setStatsError] = useState('')
  const [promoCode, setPromoCode] = useState('')
  const [promoActivity, setPromoActivity] = useState('all')
  const [promoOffset, setPromoOffset] = useState(0)
  const [promoUsers, setPromoUsers] = useState<PromoUsers | null>(null)
  const [promoUsersBusy, setPromoUsersBusy] = useState(false)
  const [promoUsersError, setPromoUsersError] = useState('')
  const [promoRefresh, setPromoRefresh] = useState(0)
  const promoSection = useRef<HTMLElement>(null)
  const scrollToPromo = useRef(false)

  useEffect(() => {
    const dialog = deleteDialog.current
    if (!dialog) return
    if (promoToDelete && !dialog.open) dialog.showModal()
    if (!promoToDelete && dialog.open) dialog.close()
  }, [promoToDelete])

  const fetchPromos = useCallback(async () => {
    const res = await fetch('/api/admin/promo', { headers: { Authorization: `Bearer ${token}` } })
    if (res.ok) setPromos(await res.json())
  }, [token])

  const fetchStats = useCallback(async () => {
    setLoadingStats(true)
    setStatsError('')
    try {
      const res = await fetch('/api/admin/bonuses/stats', { headers: { Authorization: `Bearer ${token}` } })
      if (!res.ok) throw new Error('stats')
      setStats(await res.json())
    } catch {
      setStatsError('Не удалось загрузить статистику. Повторите попытку.')
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

  useEffect(() => {
    if (tab !== 'stats') return
    const controller = new AbortController()
    setPromoUsersBusy(true)
    setPromoUsersError('')
    setPromoUsers(null)
    const params = new URLSearchParams({ offset: String(promoOffset), limit: '50', activity: promoActivity })
    if (promoCode) params.set('code', promoCode)
    fetch(`/api/admin/bonuses/promo-users?${params}`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error('promo users')
        const data: PromoUsers = await response.json()
        if (!controller.signal.aborted) setPromoUsers(data)
      }).catch(() => {
        if (!controller.signal.aborted) setPromoUsersError('Не удалось загрузить пользователей промокода. Повторите попытку.')
      }).finally(() => { if (!controller.signal.aborted) setPromoUsersBusy(false) })
    return () => controller.abort()
  }, [tab, token, promoCode, promoActivity, promoOffset, promoRefresh])

  const openPromoStats = (code: string) => {
    scrollToPromo.current = true
    setPromoCode(code)
    setPromoActivity('all')
    setPromoOffset(0)
    setTab('stats')
  }

  useEffect(() => {
    if (tab === 'stats' && scrollToPromo.current && promoSection.current) {
      promoSection.current.scrollIntoView({ block: 'start' })
      scrollToPromo.current = false
    }
  }, [tab, promoCode])

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

  const removePromo = async () => {
    if (!promoToDelete || deleting) return
    setDeleting(true)
    setDeleteError('')
    try {
      const res = await fetch(`/api/admin/promo/${encodeURIComponent(promoToDelete.id)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setDeleteError(typeof body.detail === 'string' ? body.detail : 'Не удалось удалить промокод. Повторите попытку.')
        return
      }
      setPromos(current => current.filter(p => p.id !== promoToDelete.id))
      setPromoToDelete(null)
    } catch {
      setDeleteError('Не удалось удалить промокод. Проверьте соединение и повторите попытку.')
    } finally {
      setDeleting(false)
    }
  }

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
                  <th className="text-left px-4 py-3">Пользователи</th>
                  <th className="text-left px-4 py-3">Применения при оплате</th>
                  <th className="text-left px-4 py-3">Истекает</th>
                  <th className="text-right px-4 py-3">Действия</th>
                </tr>
              </thead>
              <tbody>
                {promos.map(p => (
                  <tr key={p.id} className="border-b border-[#1a1a1a]">
                    <td className="px-4 py-3 font-mono font-bold">{p.code}</td>
                    <td className="px-4 py-3">{p.discount_percent}%</td>
                    <td className="px-4 py-3">+{p.extra_days} дн.</td>
                    <td className="px-4 py-3">
                      <button type="button" onClick={() => openPromoStats(p.code)} aria-label={`Статистика промокода ${p.code}`} className="text-left rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-400">
                        <span className="text-violet-300 hover:text-violet-200 underline underline-offset-4">{p.users_count ?? 0} с кодом</span>
                        <span className="block text-xs text-[#aaa] mt-1">Оплатили: {p.paid_users_count ?? 0} · оплатили и активны: {p.paid_active_users_count ?? 0}</span>
                      </button>
                    </td>
                    <td className="px-4 py-3 text-[#aaa] whitespace-nowrap">{p.use_count} / {p.max_uses}</td>
                    <td className="px-4 py-3 text-[#888]">{p.expires_at ? String(p.expires_at).split('T')[0] : '—'}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => { setDeleteError(''); setPromoToDelete({ id: p.id, code: p.code }) }}
                        className="p-1.5 rounded-lg transition-colors hover:bg-red-500/20 text-[#888] hover:text-red-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-400"
                        title="Удалить промокод"
                        aria-label={`Удалить промокод ${p.code}`}
                      >
                        <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                ))}
                {!promos.length && (
                  <tr><td colSpan={7} className="px-4 py-8 text-center text-[#555]">Промокодов пока нет</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      <dialog
        ref={deleteDialog}
        role="alertdialog"
        aria-labelledby="promo-delete-title"
        aria-describedby="promo-delete-description"
        onCancel={event => { if (deleting) event.preventDefault(); else setPromoToDelete(null) }}
        onClose={() => { setPromoToDelete(null); setDeleteError('') }}
        className="!m-auto w-[calc(100%_-_2rem)] max-w-md bg-[#111] text-[#e5e7eb] border border-[#222] rounded-xl p-6 backdrop:bg-black/70"
      >
        <h2 id="promo-delete-title" className="text-lg font-semibold">Удалить промокод?</h2>
        <p id="promo-delete-description" className="mt-3 text-sm text-[#aaa] leading-relaxed">
          Промокод <span className="font-mono font-semibold text-white">{promoToDelete?.code}</span> исчезнет из списка и станет недоступен для новых применений.
          {' '}Созданные платежи и выданные бонусы сохранятся.
        </p>
        {deleteError && <p role="alert" className="mt-3 text-sm text-red-400">{deleteError}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            autoFocus
            onClick={() => setPromoToDelete(null)}
            disabled={deleting}
            className="px-4 py-2 rounded-lg border border-[#333] bg-[#1a1a1a] text-sm font-medium hover:bg-[#222] disabled:opacity-50 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#888]"
          >Отмена</button>
          <button
            type="button"
            onClick={() => void removePromo()}
            disabled={deleting}
            className="px-4 py-2 rounded-lg border border-red-500/30 bg-red-500/15 text-red-400 text-sm font-medium hover:bg-red-500/25 disabled:opacity-50 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-400"
          >{deleting ? 'Удаляем…' : 'Удалить'}</button>
        </div>
      </dialog>

      {tab === 'stats' && (
        <div className="space-y-6">
          {loadingStats && !stats && <p className="text-sm text-[#666]">Загрузка…</p>}
          {statsError && <p role="alert" className="text-sm text-red-400">{statsError} <button type="button" onClick={() => void fetchStats()} className="underline underline-offset-4">Повторить</button></p>}
          {s && (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {[
                ['По рефералке', s.users_from_referral],
                ['Ожидают оплату', s.referral_pending],
                ['Награждено пар', s.referral_rewarded],
                ['Пользователей с промо', stats?.promo_summary?.users_count ?? s.users_with_pending_promo],
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

          <section ref={promoSection} className="bg-[#111] border border-[#222] rounded-xl overflow-hidden" aria-labelledby="promo-activity-title">
            <div className="px-4 py-4 border-b border-[#222] space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 id="promo-activity-title" className="font-semibold text-sm">Промокоды: оплаты и активность</h2>
                <div className="flex flex-wrap items-center gap-2">
                  <label htmlFor="promo-code-filter" className="text-xs text-[#aaa]">Промокод</label>
                  <select id="promo-code-filter" value={promoCode} onChange={event => { setPromoCode(event.target.value); setPromoOffset(0) }} className="max-w-full rounded-lg border border-[#333] bg-[#111] px-3 py-2 text-sm focus-visible:outline-violet-400">
                    <option value="">Все коды</option>
                    {(stats?.promo_campaigns || []).map((campaign: { code: string }) => <option key={campaign.code} value={campaign.code}>{campaign.code}</option>)}
                    {promoCode && !stats?.promo_campaigns?.some((c: { code: string }) => c.code === promoCode) && <option value={promoCode}>{promoCode}</option>}
                  </select>
                  <label htmlFor="promo-activity-filter" className="sr-only">Оплата и активность</label>
                  <select id="promo-activity-filter" value={promoActivity} onChange={event => { setPromoActivity(event.target.value); setPromoOffset(0) }} className="max-w-full rounded-lg border border-[#333] bg-[#111] px-3 py-2 text-sm focus-visible:outline-violet-400">
                    <option value="all">Все пользователи</option>
                    <option value="paid">Оплатившие</option>
                    <option value="paid_active">Оплатили и активны</option>
                    <option value="unpaid">Без оплат</option>
                  </select>
                  <button type="button" disabled={promoUsersBusy || loadingStats} onClick={() => { setPromoRefresh(value => value + 1); void fetchStats() }} className="rounded-lg border border-[#333] px-3 py-2 text-xs text-[#ccc] hover:bg-[#222] disabled:opacity-50">Обновить</button>
                </div>
              </div>
              {promoUsers && <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-live="polite">
                <span>Пользователей: <strong>{promoUsers.summary.users_count}</strong></span>
                <span>Оплатили: <strong>{promoUsers.summary.paid_users_count}</strong>{promoUsers.summary.users_count > 0 && <span className="text-[#aaa]"> ({(100 * promoUsers.summary.paid_users_count / promoUsers.summary.users_count).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%)</span>}</span>
                <span>Подписка действует: <strong>{promoUsers.summary.subscribed_users_count}</strong></span>
                <span>Оплатили и активны: <strong className="text-emerald-400">{promoUsers.summary.paid_active_users_count}</strong></span>
              </div>}
              <p className="text-xs text-[#aaa] leading-relaxed">Учитываются пользователи, указавшие код при регистрации или оплате. Оплаты — успешные платежи этих пользователей. «Оплатили и активны» — есть действующая подписка и активность приложения за последние 7 дней после оплаты. Регистрация сама по себе сюда не входит.</p>
            </div>
            {promoUsersBusy && <p role="status" className="px-4 py-5 text-sm text-[#aaa]">Загрузка пользователей…</p>}
            {promoUsersError && <p role="alert" className="px-4 py-5 text-sm text-red-400">{promoUsersError} <button type="button" onClick={() => setPromoRefresh(value => value + 1)} className="underline underline-offset-4">Повторить</button></p>}
            <div className="promo-mobile-users sm:hidden divide-y divide-[#222]">
              {(promoUsers?.items || []).map(u => <article key={`${u.user_id}-${u.code}`} className="px-4 py-4 space-y-2 text-sm">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0"><p className="break-words">{u.email}</p><p className="text-xs text-[#aaa] mt-1">{u.display_id}</p></div>
                  <span className="font-mono text-violet-300 shrink-0">{u.code}</span>
                </div>
                <p className={u.has_paid ? 'text-emerald-400' : 'text-[#aaa]'}>{u.has_paid ? `Оплачено ${u.paid_total.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽ · ${u.paid_count} платежей` : 'Не оплачивал'}</p>
                {u.has_paid && <p className="text-xs text-[#aaa]">Последняя оплата: {dateTime(u.last_paid_at)}</p>}
                <p className="text-xs text-[#aaa]">{u.has_active_subscription ? `Подписка до ${dateTime(u.active_until)}` : 'Нет действующей подписки'}</p>
                {u.paid_active_7d && <p className="text-emerald-400">Оплатил и активен</p>}
                {u.vpn_online && <p className="text-emerald-400">VPN онлайн</p>}
                <p className="text-xs text-[#aaa]">Последняя активность: {dateTime(u.last_seen_at)}</p>
                <p className="text-xs text-[#aaa]">Регистрация: {dateTime(u.created_at)}</p>
              </article>)}
              {!promoUsersBusy && !promoUsersError && promoUsers && !promoUsers.items.length && <p className="px-4 py-8 text-sm text-[#aaa]">Нет пользователей с выбранными условиями</p>}
            </div>
            <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-sm min-w-[820px]" aria-label="Пользователи промокодов">
              <thead>
                <tr className="border-b border-[#222] text-[#aaa] text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Пользователь</th>
                  <th className="text-left px-4 py-3">Промокод</th>
                  <th className="text-left px-4 py-3">Оплаты</th>
                  <th className="text-left px-4 py-3">Подписка</th>
                  <th className="text-left px-4 py-3">Активность</th>
                </tr>
              </thead>
              <tbody>
                {(promoUsers?.items || []).map(u => (
                  <tr key={`${u.user_id}-${u.code}`} className="border-b border-[#1a1a1a] align-top">
                    <td className="px-4 py-3 max-w-[260px]">
                      <div className="break-words">{u.email}</div>
                      <div className="text-[11px] text-[#aaa] mt-1">{u.display_id} · регистрация {dateTime(u.created_at)}</div>
                    </td>
                    <td className="px-4 py-3 font-mono font-bold">{u.code}</td>
                    <td className="px-4 py-3">
                      {u.has_paid ? <><div className="text-emerald-400">{u.paid_total.toLocaleString('ru-RU', { maximumFractionDigits: 2 })} ₽ · {u.paid_count} платежей</div><div className="text-xs text-[#aaa] mt-1">Последняя: {dateTime(u.last_paid_at)}</div></> : <span className="text-[#aaa]">Не оплачивал</span>}
                    </td>
                    <td className="px-4 py-3">
                      {u.has_active_subscription ? <><div className="text-emerald-400">Действует</div><div className="text-xs text-[#aaa] mt-1">До {dateTime(u.active_until)}</div></> : <span className="text-[#aaa]">Нет действующей</span>}
                    </td>
                    <td className="px-4 py-3">
                      {u.vpn_online && <div className="text-emerald-400">VPN онлайн</div>}
                      {u.paid_active_7d && <div className="text-emerald-400">Оплатил и активен</div>}
                      <div className="text-xs text-[#aaa] mt-1">Последняя: {dateTime(u.last_seen_at)}</div>
                    </td>
                  </tr>
                ))}
                {!promoUsersBusy && !promoUsersError && promoUsers && !promoUsers.items.length && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-[#aaa]">Нет пользователей с выбранными условиями</td></tr>
                )}
              </tbody>
            </table>
            </div>
            {promoUsers && promoUsers.total > 0 && <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-[#222] text-xs text-[#aaa]">
              <span>Записи {promoOffset + 1}–{Math.min(promoOffset + promoUsers.items.length, promoUsers.total)} из {promoUsers.total}</span>
              <div className="flex gap-2">
                <button type="button" disabled={!promoOffset || promoUsersBusy} onClick={() => setPromoOffset(value => Math.max(0, value - 50))} className="rounded-lg border border-[#333] px-3 py-2 hover:bg-[#222] disabled:opacity-40">Назад</button>
                <button type="button" disabled={promoOffset + 50 >= promoUsers.total || promoUsersBusy} onClick={() => setPromoOffset(value => value + 50)} className="rounded-lg border border-[#333] px-3 py-2 hover:bg-[#222] disabled:opacity-40">Далее</button>
              </div>
            </div>}
          </section>
        </div>
      )}
    </div>
  )
}
