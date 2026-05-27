import { useEffect, useMemo, useState } from 'react'
import {
  getExcludedApps,
  isExclusionsWhitelist,
  saveExcludedApps,
  type PcAppItem,
} from '../exclusionsStore'

interface Props {
  fg: string
  muted: string
  onBack: () => void
}

export default function AppExclusionsPanel({ fg, muted, onBack }: Props) {
  const [apps, setApps] = useState<PcAppItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(() => getExcludedApps())
  const [whitelist, setWhitelist] = useState(isExclusionsWhitelist())
  const [showSystemApps, setShowSystemApps] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const list = await (window as any).electronAPI?.listInstalledApps?.()
        if (!cancelled) setApps(Array.isArray(list) ? list : [])
      } catch {
        if (!cancelled) setApps([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const persist = (next: Set<string>, nextWhitelist = whitelist) => {
    setSelected(next)
    setWhitelist(nextWhitelist)
    saveExcludedApps(next, nextWhitelist)
  }

  const displayApps = useMemo(() => {
    return apps
      .filter(a => showSystemApps || !a.isSystem)
      .filter(a => {
        if (!search.trim()) return true
        const q = search.toLowerCase()
        return a.name.toLowerCase().includes(q) || (a.installLocation || '').toLowerCase().includes(q)
      })
      .sort((a, b) => {
        const aSel = selected.has(a.id) ? 1 : 0
        const bSel = selected.has(b.id) ? 1 : 0
        if (aSel !== bSel) return bSel - aSel
        return a.name.localeCompare(b.name, 'ru')
      })
  }, [apps, selected, search, showSystemApps])

  return (
    <div className="flex-1 p-4 overflow-y-auto">
      <button onClick={onBack} className="text-xs text-gray-400 mb-4">← Назад</button>
      <div className="text-sm font-semibold mb-1" style={{ color: fg }}>Исключения приложений</div>
      <p className="text-[11px] mb-3" style={{ color: muted }}>
        {whitelist ? 'БС: неотмеченные идут через VPN' : 'ЧС: отмеченные исключены из VPN'}
      </p>

      <div className="flex gap-2 mb-2">
        <button
          onClick={() => {
            if (whitelist) {
              const all = new Set(apps.map(a => a.id))
              const next = new Set([...all].filter(id => !selected.has(id)))
              persist(next, false)
            }
          }}
          className={`px-2 py-1 rounded-lg text-xs border ${!whitelist ? 'bg-black text-white border-black' : 'border-gray-200'}`}
        >
          ЧС
        </button>
        <button
          onClick={() => {
            if (!whitelist) {
              const all = new Set(apps.map(a => a.id))
              const next = new Set([...all].filter(id => !selected.has(id)))
              persist(next, true)
            }
          }}
          className={`px-2 py-1 rounded-lg text-xs border ${whitelist ? 'bg-black text-white border-black' : 'border-gray-200'}`}
        >
          БС
        </button>
      </div>

      <label className="flex items-center justify-between gap-2 mb-2 text-xs" style={{ color: fg }}>
        <span>Показать системные</span>
        <input
          type="checkbox"
          checked={showSystemApps}
          onChange={e => setShowSystemApps(e.target.checked)}
          className="accent-black"
        />
      </label>

      <input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Поиск..."
        className="w-full border border-gray-200 rounded-xl px-3 py-2 text-sm mb-3 focus:outline-none focus:border-black"
        style={{ userSelect: 'text' } as any}
      />

      {loading ? (
        <div className="flex justify-center py-8">
          <div className="w-5 h-5 border-2 rounded-full animate-spin border-gray-200 border-t-black" />
        </div>
      ) : (
        <div className="space-y-1">
          {displayApps.map(app => {
            const checked = selected.has(app.id)
            return (
              <button
                key={app.id}
                onClick={() => {
                  const next = new Set(selected)
                  if (checked) next.delete(app.id)
                  else next.add(app.id)
                  persist(next)
                }}
                className="w-full flex items-center gap-2 py-2 px-1 rounded-lg hover:bg-gray-50 text-left"
              >
                {app.icon ? (
                  <img src={app.icon} alt="" className="w-9 h-9 rounded-lg object-contain shrink-0" />
                ) : (
                  <div className="w-9 h-9 rounded-lg bg-gray-100 shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium truncate" style={{ color: fg }}>{app.name}</div>
                  {app.installLocation && (
                    <div className="text-[10px] truncate" style={{ color: muted }}>{app.installLocation}</div>
                  )}
                </div>
                <input type="checkbox" readOnly checked={checked} className="accent-black shrink-0" />
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
