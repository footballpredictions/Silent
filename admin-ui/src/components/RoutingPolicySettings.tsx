import { useEffect, useState } from 'react'

type Policy = { direct_domains: string[]; vpn_domains: string[]; revision: string }

export default function RoutingPolicySettings({ token }: { token: string }) {
  const [direct, setDirect] = useState('')
  const [vpn, setVpn] = useState('')
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const apply = (policy: Policy) => {
    setDirect(policy.direct_domains.join('\n'))
    setVpn(policy.vpn_domains.join('\n'))
  }
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    fetch('/api/admin/settings/routing-policy', {
      headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
    }).then(async response => {
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Не удалось загрузить список сайтов')
      if (!controller.signal.aborted) { apply(data); setLoaded(true) }
    }).catch(err => {
      if (!controller.signal.aborted) setError(String(err.message))
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [token])

  const save = async () => {
    setSaving(true)
    setError(null)
    setSaved(false)
    const lines = (value: string) => value.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    try {
      const response = await fetch('/api/admin/settings/routing-policy', {
        method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ direct_domains: lines(direct), vpn_domains: lines(vpn) }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Проверьте список сайтов')
      apply(data)
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить. Попробуйте ещё раз')
    } finally { setSaving(false) }
  }

  return <section className="rounded-xl border border-[#222] bg-[#111] p-5 space-y-4" aria-labelledby="routing-title">
    <h2 id="routing-title" className="text-sm font-medium text-white">Российские сервисы мимо VPN</h2>
    <p className="text-sm text-[#aaa]">Домен или ссылка, по одному на строку. Поддомены включены. Роутеры получают изменения автоматически.</p>
    {loading ? <p className="text-sm text-[#aaa]" role="status">Загрузка списка…</p> : <>
      <label className="block text-sm text-[#ccc]" htmlFor="routing-direct">Мимо VPN</label>
      <textarea id="routing-direct" value={direct} onChange={event => { setDirect(event.target.value); setSaved(false) }}
        disabled={saving || !loaded} rows={9} spellCheck={false}
        className="w-full rounded-lg border border-[#444] bg-[#181818] p-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50" />
      <label className="block text-sm text-[#ccc]" htmlFor="routing-vpn">Всегда через VPN</label>
      <textarea id="routing-vpn" value={vpn} onChange={event => { setVpn(event.target.value); setSaved(false) }}
        disabled={saving || !loaded} rows={4} spellCheck={false}
        className="w-full rounded-lg border border-[#444] bg-[#181818] p-3 text-sm text-white focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:opacity-50" />
      <p className="text-sm text-[#aaa]">«Всегда через VPN» имеет приоритет над обходом.</p>
      <button type="button" onClick={save} disabled={saving || !loaded}
        className="rounded-lg bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-500 focus:outline-none focus:ring-2 focus:ring-purple-400 disabled:opacity-50">
        {saving ? 'Сохранение…' : 'Сохранить сайты'}
      </button>
    </>}
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
    {saved && <p role="status" className="text-sm text-emerald-300">Сохранено. Роутеры применят список в течение пяти минут.</p>}
  </section>
}
