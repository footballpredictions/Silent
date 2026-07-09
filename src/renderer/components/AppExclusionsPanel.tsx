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
  bg: string
  fieldBg: string
  fieldText: string
  fieldPlaceholder: string
  border: string
  borderStrong: string
  dark: boolean
  onBack: () => void
}

function ThemeCheck({
  checked,
  dark,
  fg,
  bg,
}: {
  checked: boolean
  dark: boolean
  fg: string
  bg: string
}) {
  const border = dark ? '#FFFFFF' : fg
  const fill = !checked ? 'transparent' : dark ? '#000000' : fg
  const mark = dark ? '#FFFFFF' : bg
  return (
    <span
      className="shrink-0 inline-flex items-center justify-center rounded"
      style={{
        width: 18,
        height: 18,
        border: `1.5px solid ${border}`,
        background: fill,
        boxSizing: 'border-box',
      }}
      aria-hidden
    >
      {checked && (
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path
            d="M2.5 6.2L4.8 8.5L9.5 3.5"
            stroke={mark}
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </span>
  )
}

export default function AppExclusionsPanel({
  fg,
  muted,
  bg,
  fieldBg,
  fieldText,
  fieldPlaceholder,
  border,
  borderStrong,
  dark,
  onBack,
}: Props) {
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

  const inactiveBtn = {
    border: `1px solid ${borderStrong}`,
    color: fg,
    background: 'transparent',
  }
  const activeBtn = {
    border: `1px solid ${fg}`,
    color: bg,
    background: fg,
  }

  return (
    <div className="flex-1 p-4 overflow-y-auto text-left w-full self-stretch items-start">
      <button type="button" onClick={onBack} className="text-xs mb-4 block text-left" style={{ color: muted }}>
        ← Назад
      </button>
      <div className="text-sm font-bold mb-1 text-left w-full" style={{ color: fg }}>
        Исключения приложений
      </div>
      <p className="text-[11px] mb-3 text-left w-full" style={{ color: muted }}>
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
          className="px-2 py-1 rounded-lg text-xs"
          style={!whitelist ? activeBtn : inactiveBtn}
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
          className="px-2 py-1 rounded-lg text-xs"
          style={whitelist ? activeBtn : inactiveBtn}
        >
          БС
        </button>
      </div>

      <label className="flex items-center justify-between gap-2 mb-2 text-xs cursor-pointer" style={{ color: fg }}>
        <span>Показать системные</span>
        <button
          type="button"
          onClick={() => setShowSystemApps(v => !v)}
          className="p-0 border-0 bg-transparent"
          aria-pressed={showSystemApps}
        >
          <ThemeCheck checked={showSystemApps} dark={dark} fg={fg} bg={bg} />
        </button>
      </label>

      <input
        value={search}
        onChange={e => setSearch(e.target.value)}
        placeholder="Поиск..."
        className="theme-field w-full rounded-xl px-3 py-2 text-sm mb-3 focus:outline-none"
        style={{
          userSelect: 'text',
          background: fieldBg,
          color: fieldText,
          border: `1px solid ${borderStrong}`,
          ['--field-ph' as any]: fieldPlaceholder,
        } as any}
        onFocus={e => { e.currentTarget.style.borderColor = fg }}
        onBlur={e => { e.currentTarget.style.borderColor = borderStrong }}
      />

      {loading ? (
        <div className="flex justify-center py-8">
          <div
            className="w-5 h-5 border-2 rounded-full animate-spin"
            style={{ borderColor: border, borderTopColor: fg }}
          />
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
                className="w-full flex items-center gap-2 py-2 px-1 rounded-lg text-left"
                style={{ background: 'transparent' }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = dark ? '#1F1F26' : '#F9FAFB' }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'transparent' }}
              >
                {app.icon ? (
                  <img src={app.icon} alt="" className="w-9 h-9 rounded-lg object-contain shrink-0" />
                ) : (
                  <div className="w-9 h-9 rounded-lg shrink-0" style={{ background: fieldBg }} />
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium truncate" style={{ color: fg }}>{app.name}</div>
                  {app.installLocation && (
                    <div className="text-[10px] truncate" style={{ color: muted }}>{app.installLocation}</div>
                  )}
                </div>
                <ThemeCheck checked={checked} dark={dark} fg={fg} bg={bg} />
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
