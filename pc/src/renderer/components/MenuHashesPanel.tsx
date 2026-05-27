import { useEffect, useState } from 'react'
import api from '../api'

export interface HashItem {
  hash: string
  label: string
  source: string
  slot_index?: number | null
  is_active: boolean
  status: string
}

interface Props {
  fg: string
  muted: string
  onBack: () => void
}

export default function MenuHashesPanel({ fg, muted, onBack }: Props) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [items, setItems] = useState<HashItem[]>([])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await api.get('/api/vpn/hashes')
        if (cancelled) return
        const body = res.data
        if (body.items?.length) {
          setItems(body.items)
        } else {
          const hashes: string[] = body.hashes || []
          setItems(hashes.map((h, i) => ({
            hash: h,
            label: i === 0 ? 'Bootstrap' : `Сервер #${i - 1}`,
            source: i === 0 ? 'bootstrap' : 'server',
            slot_index: i === 0 ? null : i - 1,
            is_active: true,
            status: 'active',
          })))
        }
      } catch (e: any) {
        if (!cancelled) setError(e.response?.data?.detail || e.message || 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  return (
    <div className="flex-1 p-4 overflow-y-auto">
      <button onClick={onBack} className="text-xs text-gray-400 mb-4">← Назад</button>
      <div className="text-sm font-semibold mb-1" style={{ color: fg }}>Хеши</div>
      <p className="text-[11px] mb-4" style={{ color: muted }}>Хеши с сервера для VPN-туннеля</p>

      {loading && (
        <div className="flex justify-center py-8">
          <div className="w-5 h-5 border-2 rounded-full animate-spin border-gray-200 border-t-black" />
        </div>
      )}
      {error && <p className="text-xs text-red-500">{error}</p>}
      {!loading && !error && items.length === 0 && (
        <p className="text-xs" style={{ color: muted }}>Нет хешей</p>
      )}
      {items.map((item, i) => {
        const active = item.status === 'active' && item.is_active
        return (
          <div key={`${item.label}-${i}`} className="flex gap-2 py-2 border-b border-gray-100 last:border-0">
            <div className={`w-2 h-2 rounded-full mt-1 shrink-0 ${active ? 'bg-green-500' : 'bg-red-500'}`} />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-semibold" style={{ color: fg }}>
                {item.label}
                <span className={`font-normal ml-1 ${active ? 'text-green-600' : 'text-red-500'}`}>
                  · {active ? 'Активна' : 'Просрочен'}
                </span>
              </div>
              <div className="text-[10px] font-mono break-all mt-1" style={{ color: active ? muted : `${fg}55` }}>
                {item.hash}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
