import { useEffect, useMemo, useState } from 'react'
import {
  getExcludedApps,
  resetStaleExclusions,
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

/** Как ThemeCheckbox на Android: dark — чёрный фон / белая галочка / белая рамка. */
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
  const fill = !checked ? 'transparent' : dark ? '#000000' : fg
  const mark = dark ? '#FFFFFF' : bg
  return (
    <span
      className="shrink-0 inline-flex items-center justify-center rounded"
      style={{
        width: 18,
        height: 18,
        border: `1.5px solid ${dark ? '#FFFFFF' : `${fg}59`}`,
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

const STALE_RESET_KEY = 'pc_exclusions_startmenu_v1'

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
  const [loadFailed, setLoadFailed] = useState(false)
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(() => {
    // Одноразовый сброс: старые id/БС давали «всё отмечено»
    if (!localStorage.getItem(STALE_RESET_KEY)) {
      resetStaleExclusions()
      localStorage.setItem(STALE_RESET_KEY, '1')
      return new Set()
    }
    return getExcludedApps()
  })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setLoadFailed(false)
      try {
        const list = await (window as any).electronAPI?.listInstalledApps?.()
        if (cancelled) return
        const next = Array.isArray(list) ? list : []
        setApps(next)

        // Оставляем только id из текущего списка (устаревшие отсекаем)
        const valid = new Set(next.map((a: PcAppItem) => a.id))
        setSelected(prev => {
          const kept = new Set([...prev].filter(id => valid.has(id)))
          if (kept.size !== prev.size) saveExcludedApps(kept, next)
          return kept
        })

        setLoadFailed(next.length === 0)
      } catch {
        if (!cancelled) {
          setApps([])
          setLoadFailed(true)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const persist = (next: Set<string>) => {
    setSelected(next)
    saveExcludedApps(next, apps)
  }

  const displayApps = useMemo(() => {
    return apps
      .filter(a => {
        if (!search.trim()) return true
        const q = search.toLowerCase()
        return (
          a.name.toLowerCase().includes(q) ||
          (a.installLocation || '').toLowerCase().includes(q) ||
          (a.exePath || '').toLowerCase().includes(q)
        )
      })
      .sort((a, b) => {
        const aSel = selected.has(a.id) ? 1 : 0
        const bSel = selected.has(b.id) ? 1 : 0
        if (aSel !== bSel) return bSel - aSel
        return a.name.localeCompare(b.name, 'ru')
      })
  }, [apps, selected, search])

  return (
    <div className="flex-1 p-4 overflow-y-auto text-left w-full self-stretch items-start">
      <button type="button" onClick={onBack} className="text-xs mb-4 block text-left" style={{ color: muted }}>
        ← Назад
      </button>
      <div className="text-sm font-bold text-left w-full" style={{ color: fg }}>
        Исключения приложений
      </div>
      <p className="text-[11px] mt-1 mb-3 text-left w-full" style={{ color: muted }}>
        Отмеченные приложения идут мимо VPN-туннеля
      </p>

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
      ) : loadFailed && displayApps.length === 0 ? (
        <p className="text-xs py-6 text-left" style={{ color: muted }}>
          Не удалось получить список программ. Проверьте права доступа или перезапустите приложение.
        </p>
      ) : displayApps.length === 0 ? (
        <p className="text-xs py-6 text-left" style={{ color: muted }}>
          Ничего не найдено
        </p>
      ) : (
        <div className="space-y-1.5">
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
                className="w-full flex items-center gap-2.5 py-1.5 px-1 rounded-lg text-left"
                style={{ background: 'transparent' }}
                onMouseEnter={e => {
                  ;(e.currentTarget as HTMLButtonElement).style.background = dark ? '#1F1F26' : '#F9FAFB'
                }}
                onMouseLeave={e => {
                  ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                }}
              >
                {app.icon ? (
                  <img src={app.icon} alt="" className="w-9 h-9 object-contain shrink-0" />
                ) : (
                  <div
                    className="w-9 h-9 shrink-0 flex items-center justify-center text-xs font-semibold"
                    style={{ background: fieldBg, color: muted }}
                  >
                    {(app.name || '?').charAt(0).toUpperCase()}
                  </div>
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] truncate" style={{ color: fg }}>{app.name}</div>
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
