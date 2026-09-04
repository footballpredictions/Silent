import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  getBlacklistApps,
  getExcludedApps,
  getSiteBypassRules,
  getWhitelistApps,
  isExclusionsWhitelist,
  resetStaleExclusions,
  saveExcludedApps,
  saveExceptionsMode,
  saveSiteBypassRules,
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
  primaryBtnBg: string
  primaryBtnFg: string
  onBack: () => void
}

type Pane = 'sites' | 'apps'

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

function ModeChip({
  label,
  active,
  fg,
  bg,
  onClick,
}: {
  label: string
  active: boolean
  fg: string
  bg: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-xs px-3 py-1.5 rounded-lg"
      style={{
        background: active ? fg : 'transparent',
        color: active ? bg : fg,
        border: `1px solid ${active ? fg : `${fg}40`}`,
      }}
    >
      {label}
    </button>
  )
}

function SearchField({
  value,
  onChange,
  placeholder,
  fieldBg,
  fieldText,
  fieldPlaceholder,
  borderStrong,
  fg,
  muted,
  className = 'mb-3',
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  fieldBg: string
  fieldText: string
  fieldPlaceholder: string
  borderStrong: string
  fg: string
  muted: string
  className?: string
}) {
  return (
    <div className={`relative w-full ${className}`}>
      <input
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="theme-field w-full rounded-xl px-3 py-2 text-sm focus:outline-none pr-9"
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
      {value.trim() ? (
        <button
          type="button"
          aria-label="Очистить поиск"
          title="Очистить"
          onClick={() => onChange('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 w-6 h-6 rounded-md flex items-center justify-center"
          style={{ color: muted }}
          onMouseEnter={e => { e.currentTarget.style.color = fg }}
          onMouseLeave={e => { e.currentTarget.style.color = muted }}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
            <path d="M3 3l8 8M11 3L3 11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      ) : null}
    </div>
  )
}

const STALE_RESET_KEY = 'pc_exclusions_startmenu_v2'
const MAX_SITE_RULES = 100

function normalizeSiteRule(raw: string): string {
  let s = raw.trim()
  if (!s) return ''
  if (/^https?:\/\//i.test(s)) {
    try { s = new URL(s).hostname || s } catch { /* keep */ }
  } else if (s.includes('/') && !/^\d+\.\d+\.\d+\.\d+\/\d{1,2}$/.test(s)) {
    const before = s.split('/')[0]
    if (!/^\d+\.\d+\.\d+\.\d+$/.test(before)) s = before
  }
  return s.trim().replace(/\.$/, '')
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
  primaryBtnBg,
  primaryBtnFg,
  onBack,
}: Props) {
  const [pane, setPane] = useState<Pane>('apps')
  const [apps, setApps] = useState<PcAppItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [search, setSearch] = useState('')
  const [whitelist, setWhitelist] = useState(() => isExclusionsWhitelist())
  const [selected, setSelected] = useState<Set<string>>(() => {
    if (!localStorage.getItem(STALE_RESET_KEY)) {
      resetStaleExclusions()
      localStorage.setItem(STALE_RESET_KEY, '1')
      return new Set()
    }
    return getExcludedApps()
  })

  const [siteRules, setSiteRules] = useState<string[]>(() => getSiteBypassRules())
  const [newRule, setNewRule] = useState('')
  const [siteHint, setSiteHint] = useState<string | null>(null)
  const [siteBusy, setSiteBusy] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [whitelist])

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

        const valid = new Set(next.map((a: PcAppItem) => a.id))
        setSelected(prev => {
          const kept = new Set([...prev].filter(id => valid.has(id)))
          if (kept.size !== prev.size) saveExcludedApps(kept, next, whitelist)
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

  const persistApps = (next: Set<string>, wl = whitelist) => {
    setSelected(next)
    setWhitelist(wl)
    saveExcludedApps(next, apps, wl)
  }

  const switchMode = (toWhitelist: boolean) => {
    if (whitelist === toWhitelist) return
    setWhitelist(toWhitelist)
    const next = toWhitelist ? getWhitelistApps() : getBlacklistApps()
    setSelected(next)
    saveExceptionsMode(toWhitelist, apps)
    scrollRef.current?.scrollTo({ top: 0 })
  }

  const persistSites = async (rules: string[]) => {
    setSiteBusy(true)
    setSiteHint(null)
    try {
      const capped = rules.slice(0, MAX_SITE_RULES)
      setSiteRules(capped)
      saveSiteBypassRules(capped)
      const res = await (window as any).electronAPI?.saveSiteBypass?.({ rules: capped })
      if (res?.unresolved?.length) {
        setSiteHint(`Не резолвится: ${res.unresolved.slice(0, 2).join(', ')}`)
      } else if (res?.targets?.length) {
        setSiteHint(`Маршрутов: ${res.targets.length}`)
      }
    } catch (e: any) {
      setSiteHint(`Ошибка: ${e?.message || e}`)
    } finally {
      setSiteBusy(false)
    }
  }

  const addSiteRule = () => {
    const rule = normalizeSiteRule(newRule)
    if (!rule || siteBusy) return
    if (siteRules.some(r => r.toLowerCase() === rule.toLowerCase())) {
      setSiteHint('Уже в списке')
      setNewRule('')
      return
    }
    if (siteRules.length >= MAX_SITE_RULES) {
      setSiteHint(`Лимит ${MAX_SITE_RULES} сайтов`)
      return
    }
    setNewRule('')
    void persistSites([...siteRules, rule])
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
  const visibleIds = displayApps.map(app => app.id)
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => selected.has(id))

  const toggleSelectAll = () => {
    if (visibleIds.length === 0) return
    const next = new Set(selected)
    if (allVisibleSelected) {
      for (const id of visibleIds) next.delete(id)
    } else {
      for (const id of visibleIds) next.add(id)
    }
    persistApps(next)
  }

  return (
    <div ref={scrollRef} className="flex-1 p-4 overflow-y-auto text-left w-full self-stretch items-start">
      <button type="button" onClick={onBack} className="text-xs mb-4 block text-left" style={{ color: muted }}>
        ← Назад
      </button>
      <div className="text-sm font-bold text-left w-full" style={{ color: fg }}>
        Исключения
      </div>

      <div className="flex gap-2 mt-3 mb-3">
        <ModeChip label="Сайты" active={pane === 'sites'} fg={fg} bg={bg} onClick={() => setPane('sites')} />
        <ModeChip label="Приложения" active={pane === 'apps'} fg={fg} bg={bg} onClick={() => setPane('apps')} />
      </div>

      {pane === 'sites' ? (
        <>
          <p className="text-[11px] mb-3 text-left w-full" style={{ color: muted }}>
            Домен или IP идут мимо VPN (ozon.ru, 1.2.3.4, 10.0.0.0/8)
          </p>
          <input
            value={newRule}
            onChange={e => setNewRule(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') addSiteRule() }}
            placeholder="домен или IP…"
            disabled={siteBusy}
            className="theme-field w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none mb-2"
            style={{
              background: fieldBg,
              color: fieldText,
              border: `1px solid ${borderStrong}`,
              ['--field-ph' as any]: fieldPlaceholder,
            } as any}
          />
          <button
            type="button"
            onClick={addSiteRule}
            disabled={siteBusy || !newRule.trim()}
            className="w-full rounded-xl py-2.5 text-sm font-semibold mb-2 disabled:opacity-40 transition-opacity"
            style={{ background: primaryBtnBg, color: primaryBtnFg }}
          >
            Добавить
          </button>
          {siteHint && (
            <p className="text-[11px] mb-2" style={{ color: muted }}>{siteHint}</p>
          )}
          <p className="text-[10px] mb-2" style={{ color: muted }}>
            {siteRules.length} / {MAX_SITE_RULES}
          </p>
          {siteRules.length === 0 ? (
            <p className="text-xs py-6 text-left" style={{ color: muted }}>
              Список пуст. Добавьте домен или IP.
            </p>
          ) : (
            <div className="space-y-1">
              {siteRules.map(rule => (
                <div
                  key={rule}
                  className="flex items-center gap-2 py-1.5 px-1"
                >
                  <span className="flex-1 text-[13px] truncate" style={{ color: fg }}>{rule}</span>
                  <button
                    type="button"
                    disabled={siteBusy}
                    onClick={() => void persistSites(siteRules.filter(r => r !== rule))}
                    className="text-xs px-2"
                    style={{ color: muted }}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <>
          <p className="text-[11px] mb-2 text-left w-full" style={{ color: muted }}>
            {whitelist ? 'БС: только выбранные через VPN' : 'ЧС: выбранные мимо VPN'}
          </p>
          <div className="flex gap-2 mb-3">
            <ModeChip label="ЧС" active={!whitelist} fg={fg} bg={bg} onClick={() => switchMode(false)} />
            <ModeChip label="БС" active={whitelist} fg={fg} bg={bg} onClick={() => switchMode(true)} />
          </div>
          <div
            className="w-full flex items-center justify-between mb-2"
            onClick={() => { if (visibleIds.length > 0) toggleSelectAll() }}
            style={{ cursor: visibleIds.length > 0 ? 'pointer' : 'default', opacity: visibleIds.length > 0 ? 1 : 0.45 }}
          >
            <span className="text-xs" style={{ color: fg }}>
              Выделить все
            </span>
            <ThemeCheck checked={allVisibleSelected} dark={dark} fg={fg} bg={bg} />
          </div>

          <SearchField
            value={search}
            onChange={setSearch}
            placeholder="Поиск..."
            fieldBg={fieldBg}
            fieldText={fieldText}
            fieldPlaceholder={fieldPlaceholder}
            borderStrong={borderStrong}
            fg={fg}
            muted={muted}
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
                      persistApps(next)
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
        </>
      )}
    </div>
  )
}
