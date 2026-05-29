import { useCallback, useEffect, useState } from 'react'
import api from '../api'
import {
  formatSavedAt,
  getSavedHashItems,
  getSavedHashItemsUpdatedAt,
  mapHashesResponse,
  saveHashItems,
  type HashItem,
} from '../hashItemsStore'

interface Props {
  fg: string
  muted: string
  onBack: () => void
}

export default function MenuHashesPanel({ fg, muted, onBack }: Props) {
  const cached = getSavedHashItems()
  const [loading, setLoading] = useState(cached.length === 0)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [items, setItems] = useState<HashItem[]>(cached)
  const [savedAt, setSavedAt] = useState(getSavedHashItemsUpdatedAt())
  const [refreshKey, setRefreshKey] = useState(0)

  const refreshFromServer = useCallback(async () => {
    setSyncing(true)
    setError(null)
    try {
      const res = await api.get('/api/vpn/hashes')
      const downloaded = mapHashesResponse(res.data)
      if (downloaded.length > 0) {
        saveHashItems(downloaded)
        setItems(downloaded)
        setSavedAt(getSavedHashItemsUpdatedAt())
      } else {
        setItems(prev => {
          if (prev.length === 0) setError('На сервере пока нет хешей')
          return prev
        })
      }
    } catch (e: any) {
      setItems(prev => {
        if (prev.length === 0) {
          setError(e.response?.data?.detail || e.message || 'Не удалось загрузить хеши')
        }
        return prev
      })
    } finally {
      setSyncing(false)
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (refreshKey === 0) {
      setItems(getSavedHashItems())
      setSavedAt(getSavedHashItemsUpdatedAt())
    }
    void refreshFromServer()
  }, [refreshKey, refreshFromServer])

  return (
    <div className="flex-1 p-4 overflow-y-auto text-left w-full items-start">
      <button type="button" onClick={onBack} className="text-xs text-gray-400 mb-4 block text-left">
        ← Назад
      </button>
      <div className="text-sm font-semibold mb-1 text-left" style={{ color: fg }}>
        Хеши
      </div>
      <p className="text-[11px] mb-1 text-left" style={{ color: muted }}>
        Сохранены на устройстве и обновляются с сервера
      </p>
      {savedAt > 0 && (
        <p className="text-[10px] mb-2 text-left" style={{ color: muted }}>
          Последнее обновление: {formatSavedAt(savedAt)}
        </p>
      )}
      <button
        type="button"
        disabled={syncing}
        onClick={() => setRefreshKey(k => k + 1)}
        className="text-[11px] mb-3 text-left hover:opacity-70 disabled:opacity-40"
        style={{ color: fg }}
      >
        {syncing ? 'Обновление…' : 'Обновить с сервера'}
      </button>

      {loading && (
        <div className="flex justify-center py-8">
          <div className="w-5 h-5 border-2 rounded-full animate-spin border-gray-200 border-t-black" />
        </div>
      )}
      {error && items.length === 0 && <p className="text-xs text-red-500 text-left">{error}</p>}
      {!loading && items.length === 0 && !error && (
        <p className="text-xs text-left" style={{ color: muted }}>
          Нет хешей. Добавьте bootstrap на входе или попросите админа.
        </p>
      )}
      {syncing && items.length > 0 && (
        <p className="text-[10px] mb-2 text-left" style={{ color: muted }}>
          Обновление с сервера…
        </p>
      )}
      {error && items.length > 0 && (
        <p className="text-[11px] text-red-500 mb-2 text-left">{error}</p>
      )}
      {items.map((item, i) => {
        const active = item.status === 'active' && item.is_active
        return (
          <div key={`${item.label}-${i}`} className="flex gap-2 py-2 border-b border-gray-100 last:border-0 text-left">
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
