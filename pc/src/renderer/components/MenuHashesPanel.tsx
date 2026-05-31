import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '../api'
import {
  MAX_HASHES,
  WORKERS_PER_GROUP,
  getTotalWorkers,
  maxTotalWorkers,
  normalizeTotalWorkers,
  saveTotalWorkers,
  signalBars,
  workersForHashSlot,
} from '../hashChannelHelper'
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
  vpnConnected?: boolean
  activeWorkers?: number
}

function SignalBars({ bars, fg }: { bars: number; fg: string }) {
  return (
    <div className="flex items-end gap-0.5 shrink-0">
      {[0, 1, 2, 3].map(i => (
        <div
          key={i}
          className="w-[3px] rounded-sm"
          style={{
            height: 6 + i * 3,
            background: i < bars ? '#22C55E' : `${fg}26`,
          }}
        />
      ))}
    </div>
  )
}

export default function MenuHashesPanel({ fg, muted, onBack, vpnConnected = false, activeWorkers = 0 }: Props) {
  const cached = getSavedHashItems()
  const [loading, setLoading] = useState(cached.length === 0)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [items, setItems] = useState<HashItem[]>(cached)
  const [savedAt, setSavedAt] = useState(getSavedHashItemsUpdatedAt())
  const [refreshKey, setRefreshKey] = useState(0)

  const serverItems = items.filter(i => i.source !== 'bootstrap')
  const activeHashCount = Math.min(
    Math.max(serverItems.filter(i => i.status === 'active' && i.is_active && i.hash?.trim()).length, 1),
    MAX_HASHES,
  )
  const maxTotal = maxTotalWorkers(activeHashCount)
  const [totalWorkers, setTotalWorkers] = useState(() => getTotalWorkers(activeHashCount))

  useEffect(() => {
    setTotalWorkers(getTotalWorkers(activeHashCount))
  }, [activeHashCount])

  const stepped = useMemo(
    () => normalizeTotalWorkers(totalWorkers, activeHashCount),
    [totalWorkers, activeHashCount],
  )

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

  const serverHashRows = serverItems.filter(i => i.source !== 'bootstrap')

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

      <div className="rounded-xl border border-gray-100 p-3 mb-3 text-left" style={{ borderColor: `${fg}20` }}>
        <div className="flex items-center justify-between mb-1">
          <div className="text-[11px] font-semibold" style={{ color: fg }}>
            Сила каналов
          </div>
          <div className="text-base font-bold" style={{ color: fg }}>
            {stepped}
          </div>
        </div>
        <p className="text-[10px] mb-3" style={{ color: muted }}>
          Потоков: {stepped} из {maxTotal} (шаг 9, до {activeHashCount} хеш × 27)
        </p>
        <input
          type="range"
          min={WORKERS_PER_GROUP}
          max={maxTotal}
          step={WORKERS_PER_GROUP}
          value={stepped}
          disabled={vpnConnected}
          onChange={e => {
            const next = normalizeTotalWorkers(Number(e.target.value), activeHashCount)
            setTotalWorkers(next)
            saveTotalWorkers(next, activeHashCount)
          }}
          className="w-full accent-current"
          style={{ color: fg }}
        />
        <p className="text-[9px] mt-2" style={{ color: muted }}>
          9 → 18 → 27 → 36… — каждые +9 добавляется хеш (в libclient уходит только n÷9 хешей)
        </p>
      </div>

      {vpnConnected && (
        <p className="text-[10px] mb-2 text-left" style={{ color: muted }}>
          Активных каналов: {activeWorkers} / {stepped}
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
      {!loading && serverHashRows.length === 0 && !error && (
        <p className="text-xs text-left" style={{ color: muted }}>
          Нет серверных хешей. Попросите админа выдать слоты.
        </p>
      )}
      {syncing && serverHashRows.length > 0 && (
        <p className="text-[10px] mb-2 text-left" style={{ color: muted }}>
          Обновление с сервера…
        </p>
      )}
      {error && items.length > 0 && (
        <p className="text-[11px] text-red-500 mb-2 text-left">{error}</p>
      )}
      {serverHashRows.map((item, i) => {
        const active = item.status === 'active' && item.is_active
        const bars = vpnConnected && active ? signalBars(activeWorkers, stepped) : 0
        const maxChannels = workersForHashSlot(stepped, i, activeHashCount)
        return (
          <div key={`${item.label}-${i}`} className="flex gap-2 py-2 border-b border-gray-100 last:border-0 text-left">
            <div className={`w-2 h-2 rounded-full mt-1 shrink-0 ${active ? 'bg-green-500' : 'bg-red-500'}`} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-semibold min-w-0" style={{ color: fg }}>
                  {item.label}
                  <span className={`font-normal ml-1 ${active ? 'text-green-600' : 'text-red-500'}`}>
                    · {active ? 'Активна' : 'Просрочен'}
                  </span>
                </div>
                {active && bars > 0 && <SignalBars bars={bars} fg={fg} />}
              </div>
              <div className="text-[10px] font-mono break-all mt-1" style={{ color: active ? muted : `${fg}55` }}>
                {item.hash}
              </div>
              {active && maxChannels > 0 && (
                <div className="text-[9px] mt-0.5" style={{ color: muted }}>
                  до {maxChannels} каналов
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
