import { useCallback, useEffect, useMemo, useState } from 'react'
import { Cpu, Users, Wifi, Hash, RefreshCw, ChevronDown, ChevronRight, Activity, Server } from 'lucide-react'
import SearchInput from '../components/SearchInput'
import SortSelect from '../components/SortSelect'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

const DASHBOARD_USER_SORT_KEY = 'admin.dashboard.userSort'
const DASHBOARD_NODE_KEY = 'admin.dashboard.resourceNode'

const DASHBOARD_USER_SORTS = [
  { value: 'online', label: 'Онлайн сначала' },
  { value: 'email_az', label: 'По алфавиту А→Я' },
  { value: 'email_za', label: 'По алфавиту Я→А' },
  { value: 'registered_new', label: 'Новые сначала' },
  { value: 'registered_old', label: 'Старые сначала' },
  { value: 'last_seen', label: 'Недавно в сети' },
] as const

type DashboardUserSort = (typeof DASHBOARD_USER_SORTS)[number]['value']

function readStoredSort(key: string, fallback: string, allowed: readonly string[]): string {
  try {
    const raw = localStorage.getItem(key)
    if (raw && allowed.includes(raw)) return raw
  } catch { /* private mode */ }
  return fallback
}

function parseAdminTs(iso?: string | null): number {
  if (!iso) return 0
  let s = String(iso).trim()
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) {
    s = s.replace(' ', 'T')
    if (!s.endsWith('Z')) s += 'Z'
  }
  const t = new Date(s).getTime()
  return Number.isNaN(t) ? 0 : t
}

interface ResourceNode {
  id: string
  name: string
  title: string
  is_queen: boolean
  status?: string
}

interface Stats {
  system: {
    node_id?: string
    cpu_percent: number
    cpu_model?: string | null
    cpu_cores?: number | null
    cpu_freq_base_mhz?: number | null
    cpu_freq_current_mhz?: number | null
    cpu_freq_estimated?: boolean
    memory_total_gb: number
    memory_used_gb: number
    memory_percent: number
    disk_total_gb?: number | null
    disk_used_gb?: number | null
    disk_percent?: number | null
    network_interface?: string | null
    network_mbps_rx?: number
    network_mbps_tx?: number
    network_util_percent?: number
    network_link_capacity_mbps?: number
    reachable?: boolean
    cpu_percent_scope?: string
  }
  resource_nodes?: ResourceNode[]
  users: {
    total: number
    active_subscriptions: number
    subscriptions_paid?: number
    subscriptions_granted?: number
    subscriptions_trial?: number
    vpn_access_users?: number
    connected_devices: number
    peak_online_devices?: number
    peak_online_at?: string | null
  }
  vk_hashes: Array<{
    slot: number
    hash: string
    user_email?: string
    user_connected?: boolean
    is_active: boolean
    fail_count: number
    last_checked: string | null
  }>
  vk_users?: Array<{
    user_id: string
    user_email: string
    user_connected: boolean
    last_seen_at?: string | null
    created_at?: string | null
    device_names?: string[]
    online_device_names?: string[]
    online_devices?: Array<{ name: string; node: string }>
    slots_filled: number
    slots_max: number
    hashes: Array<{
      slot: number
      hash: string
      is_active: boolean
      fail_count: number
      last_checked: string | null
    }>
  }>
  vk_hash_summary?: {
    total_active: number
    per_user_active: number
    legacy_orphan: number
    users_total: number
    users_with_any: number
    users_complete: number
    slots_max: number
  }
}

const StatCard = ({ icon: Icon, label, value, sub, color = 'white' }: any) => (
  <div className="bg-[#111] border border-[#222] rounded-xl p-5">
    <div className="flex items-center justify-between mb-3">
      <span className="text-[#666] text-xs uppercase tracking-wider">{label}</span>
      <Icon className={`w-4 h-4 text-${color}-400`} />
    </div>
    <div className="text-2xl font-bold">{value}</div>
    {sub && <div className="text-[#555] text-xs mt-1">{sub}</div>}
  </div>
)

const formatGhz = (mhz: number) => `${(mhz / 1000).toFixed(2)} GHz`
const formatLiveMhz = (mhz: number) => `${mhz.toFixed(1)} MHz`

const formatBandwidth = (mbps: number) => {
  if (mbps >= 1) return `${mbps.toFixed(1)} Мбит/с`
  if (mbps >= 0.001) return `${(mbps * 1000).toFixed(0)} Кбит/с`
  return '0 Мбит/с'
}

const ProgressBar = ({ percent, label }: { percent: number; label: string }) => (
  <div className="mb-3">
    <div className="flex justify-between text-xs text-[#666] mb-1">
      <span>{label}</span>
      <span>{percent.toFixed(0)}%</span>
    </div>
    <div className="h-1.5 bg-[#222] rounded-full overflow-hidden">
      <div
        className={`h-full rounded-full transition-all ${percent > 80 ? 'bg-red-400' : percent > 60 ? 'bg-yellow-400' : 'bg-white'}`}
        style={{ width: `${Math.min(percent, 100)}%` }}
      />
    </div>
  </div>
)

type HistoryPoint = { t: string; v: number }

function LoadAreaChart({
  title,
  subtitle,
  data,
  stroke,
  fill,
  seriesLabel,
  emptyHint,
}: {
  title: string
  subtitle?: string
  data: HistoryPoint[]
  stroke: string
  fill: string
  seriesLabel: string
  emptyHint?: string
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <h3 className="text-xs text-[#666] uppercase tracking-wider">{title}</h3>
        {subtitle && <span className="text-[10px] text-[#555] truncate">{subtitle}</span>}
      </div>
      <ResponsiveContainer width="100%" height={96}>
        <AreaChart data={data}>
          <XAxis dataKey="t" hide />
          <YAxis domain={[0, 100]} hide />
          <Tooltip
            contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: 8, fontSize: 12 }}
            formatter={(v: number) => [`${v.toFixed(1)}%`, seriesLabel]}
          />
          <Area type="monotone" dataKey="v" stroke={stroke} fill={fill} strokeWidth={1.5} dot={false} />
        </AreaChart>
      </ResponsiveContainer>
      {data.length <= 1 && emptyHint && (
        <p className="text-[10px] text-[#555] mt-1">{emptyHint}</p>
      )}
    </div>
  )
}

function VkHashesCard({
  hashes,
  vkUsers,
  summary,
}: {
  hashes: Stats['vk_hashes']
  vkUsers?: Stats['vk_users']
  summary?: Stats['vk_hash_summary']
}) {
  const formatLastSeen = (iso?: string | null): string => {
    if (!iso) return '—'
    try {
      // Backend пишет naive UTC (datetime.utcnow).isoformat() без Z —
      // без суффикса JS считает строку «локальным» временем и МСК уезжает на −3ч.
      let s = String(iso).trim()
      if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(s) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) {
        s = s.replace(' ', 'T')
        if (!s.endsWith('Z')) s += 'Z'
      }
      const dt = new Date(s)
      if (Number.isNaN(dt.getTime())) return '—'
      return dt.toLocaleString('ru-RU', {
        timeZone: 'Europe/Moscow',
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return '—'
    }
  }

  const formatReg = (iso?: string | null): string => {
    const t = parseAdminTs(iso)
    if (!t) return ''
    return new Date(t).toLocaleDateString('ru-RU', {
      timeZone: 'Europe/Moscow',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    })
  }

  const users =
    vkUsers && vkUsers.length > 0
      ? vkUsers.map(u => [u.user_email, u] as const)
      : Object.entries(
          hashes.reduce<Record<string, Stats['vk_hashes']>>((acc, h) => {
            const key = h.user_email || '—'
            if (!acc[key]) acc[key] = []
            acc[key].push(h)
            return acc
          }, {})
        ).map(([email, slots]) => [
          email,
          {
            user_email: email,
            user_connected: slots[0]?.user_connected ?? false,
            last_seen_at: null,
            created_at: null,
            device_names: [],
            online_device_names: [],
            slots_filled: slots.length,
            slots_max: 4,
            hashes: slots.map(h => ({
              slot: h.slot,
              hash: h.hash,
              is_active: h.is_active,
              fail_count: h.fail_count,
              last_checked: h.last_checked,
            })),
          },
        ] as const)

  const [open, setOpen] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(users.map(([email]) => [email, false]))
  )
  const [userSearch, setUserSearch] = useState('')
  const [userSort, setUserSort] = useState<DashboardUserSort>(
    () => readStoredSort(DASHBOARD_USER_SORT_KEY, 'online', DASHBOARD_USER_SORTS.map(s => s.value)) as DashboardUserSort
  )

  const setAndStoreSort = (value: string) => {
    const next = (DASHBOARD_USER_SORTS.some(s => s.value === value) ? value : 'online') as DashboardUserSort
    setUserSort(next)
    try { localStorage.setItem(DASHBOARD_USER_SORT_KEY, next) } catch { /* ignore */ }
  }

  const filteredUsers = useMemo(() => {
    const q = userSearch.trim().toLowerCase()
    const matched = !q
      ? [...users]
      : users.filter(([email, u]) => {
          if (email.toLowerCase().includes(q)) return true
          const names = [
            ...('device_names' in u && u.device_names ? u.device_names : []),
            ...('online_device_names' in u && u.online_device_names ? u.online_device_names : []),
          ]
          return names.some(n => n.toLowerCase().includes(q))
        })
    const connectedOf = (u: (typeof users)[number][1]) =>
      'user_connected' in u ? Number(Boolean(u.user_connected)) : 0
    const createdOf = (u: (typeof users)[number][1]) =>
      parseAdminTs('created_at' in u ? u.created_at : null)
    const seenOf = (u: (typeof users)[number][1]) =>
      parseAdminTs('last_seen_at' in u ? u.last_seen_at : null)
    matched.sort(([emailA, a], [emailB, b]) => {
      switch (userSort) {
        case 'online': {
          const byOnline = connectedOf(b) - connectedOf(a)
          if (byOnline) return byOnline
          const bySeen = seenOf(b) - seenOf(a)
          if (bySeen) return bySeen
          return emailA.localeCompare(emailB, 'ru', { sensitivity: 'base' })
        }
        case 'email_az':
          return emailA.localeCompare(emailB, 'ru', { sensitivity: 'base' })
        case 'email_za':
          return emailB.localeCompare(emailA, 'ru', { sensitivity: 'base' })
        case 'registered_new':
          return createdOf(b) - createdOf(a) || emailA.localeCompare(emailB, 'ru', { sensitivity: 'base' })
        case 'registered_old':
          return createdOf(a) - createdOf(b) || emailA.localeCompare(emailB, 'ru', { sensitivity: 'base' })
        case 'last_seen':
          return seenOf(b) - seenOf(a) || emailA.localeCompare(emailB, 'ru', { sensitivity: 'base' })
        default:
          return 0
      }
    })
    return matched
  }, [users, userSearch, userSort])

  const toggle = (email: string) =>
    setOpen(prev => ({ ...prev, [email]: !prev[email] }))

  const summaryLine = summary
    ? `${summary.users_total} пользователей · ${summary.per_user_active} хешей у пользователей · ${summary.users_complete} с полным набором (${summary.slots_max}/${summary.slots_max})`
    : `${hashes.length} активных хешей`

  return (
    <div className="bg-[#111] border border-[#222] rounded-xl p-5">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-1">
        <h3 className="text-xs text-[#666] uppercase tracking-wider flex items-center gap-2 shrink-0">
          <Hash className="w-3.5 h-3.5" /> Серверные VK-хеши (по пользователям)
        </h3>
        <div className="flex flex-col sm:flex-row gap-2 sm:ml-auto w-full sm:w-auto">
          <SearchInput
            value={userSearch}
            onChange={setUserSearch}
            placeholder="Поиск по email или устройству…"
            className="flex-1 sm:w-56 w-full"
          />
          <SortSelect
            value={userSort}
            onChange={setAndStoreSort}
            options={[...DASHBOARD_USER_SORTS]}
            className="sm:w-48 w-full"
            label="Сортировка пользователей"
          />
        </div>
      </div>
      <p className="text-[10px] text-[#555] mb-4">{summaryLine}</p>
      {summary && summary.legacy_orphan > 0 && (
        <p className="text-[10px] text-amber-400/80 mb-3">
          {summary.legacy_orphan} старых хешей без привязки к пользователю (legacy) — не отображаются в списке ниже.
          Всего активных: {summary.total_active}.
        </p>
      )}

      {users.length === 0 && (
        <p className="text-[#555] text-sm">Нет пользователей. Подключите AI-агента в разделе VK.</p>
      )}

      {users.length > 0 && filteredUsers.length === 0 && (
        <p className="text-[#555] text-sm">Никого не найдено по запросу «{userSearch.trim()}».</p>
      )}

      <div className="space-y-1">
        {filteredUsers.map(([email, u]) => {
          const isOpen = open[email]
          const slots = 'hashes' in u ? u.hashes : []
          const filled = 'slots_filled' in u ? u.slots_filled : slots.length
          const max = 'slots_max' in u ? u.slots_max : 4
          const connected = 'user_connected' in u ? u.user_connected : false
          const registered = 'created_at' in u ? formatReg(u.created_at) : ''
          return (
            <div key={email} className="border border-[#1e1e1e] rounded-lg overflow-hidden">
              <button
                onClick={() => toggle(email)}
                className="w-full px-3 py-2.5 hover:bg-[#181818] transition-colors text-left"
              >
                <div className="flex items-center gap-2 min-w-0">
                  {isOpen
                    ? <ChevronDown className="w-3.5 h-3.5 text-[#555] shrink-0" />
                    : <ChevronRight className="w-3.5 h-3.5 text-[#555] shrink-0" />
                  }
                  <div className={`w-2 h-2 rounded-full shrink-0 ${
                    connected ? 'bg-green-400 shadow-[0_0_5px_#4ade80]' : 'bg-[#444]'
                  }`} />
                  <span className="text-sm text-white flex-1 min-w-0 truncate">{email}</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full shrink-0 ${
                    filled >= max ? 'text-green-400/90 bg-green-400/10' : filled > 0 ? 'text-amber-400/90 bg-amber-400/10' : 'text-[#555] bg-[#222]'
                  }`}>
                    {filled} / {max}
                  </span>
                </div>
                <div className="mt-1 ml-[26px] text-[10px] min-w-0 truncate">
                  {connected ? (
                    <span className="text-green-400">
                      Онлайн:{' '}
                      {('online_devices' in u && u.online_devices && u.online_devices.length > 0)
                        ? u.online_devices.map(d => `${d.name} · ${d.node}`).join(', ')
                        : ('online_device_names' in u && u.online_device_names && u.online_device_names.length > 0)
                          ? u.online_device_names.join(', ')
                          : 'устройство не определено'}
                      {registered ? ` · Рег.: ${registered}` : ''}
                    </span>
                  ) : (
                    <span className="text-[#666]">
                      Последний вход (МСК): {formatLastSeen('last_seen_at' in u ? u.last_seen_at : null)}
                      {' · '}
                      Устройства: {('device_names' in u && u.device_names && u.device_names.length > 0) ? u.device_names.join(', ') : '—'}
                      {registered ? ` · Рег.: ${registered}` : ''}
                    </span>
                  )}
                </div>
              </button>

              {isOpen && (
                <div className="border-t border-[#1e1e1e] divide-y divide-[#1a1a1a]">
                  {filled === 0 && (
                    <p className="px-3 py-2.5 text-xs text-[#555] italic bg-[#0f0f0f]">
                      Нет серверных хешей — агент добавит при следующей проверке (~5 мин) или «Создать хеши» в VK.
                    </p>
                  )}
                  {slots.map((h, i) => (
                    <div key={i} className="px-3 py-2.5 bg-[#0f0f0f]">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-[10px] text-[#555] bg-[#1a1a1a] px-1.5 py-0.5 rounded">
                          Слот {h.slot}
                        </span>
                        <span className={`text-[10px] ${h.fail_count > 0 ? 'text-red-400' : 'text-[#333]'}`}>
                          ⚠ {h.fail_count} сбоев
                        </span>
                      </div>
                      <div className="font-mono text-[11px] text-[#666] break-all leading-relaxed select-all">
                        {h.hash}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function DashboardPage({ token, onUnauthorized }: { token: string; onUnauthorized?: () => void }) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [cpuHistory, setCpuHistory] = useState<HistoryPoint[]>([])
  const [netHistory, setNetHistory] = useState<HistoryPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [nodeId, setNodeId] = useState(() => {
    try {
      return localStorage.getItem(DASHBOARD_NODE_KEY) || 'queen'
    } catch {
      return 'queen'
    }
  })

  const resourceNodes = stats?.resource_nodes ?? [{ id: 'queen', name: 'Улей', title: 'Улей', is_queen: true }]

  const selectNode = useCallback((id: string) => {
    setNodeId(id)
    try { localStorage.setItem(DASHBOARD_NODE_KEY, id) } catch { /* private mode */ }
    setCpuHistory([])
    setNetHistory([])
  }, [])

  const fetchStats = useCallback(async (mode: 'full' | 'light' = 'full') => {
    if (mode === 'full') setLoading(true)
    try {
      const params = new URLSearchParams()
      if (mode === 'light') params.set('light', '1')
      params.set('node_id', nodeId)
      const res = await fetch(`/api/admin/stats?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.status === 401) {
        onUnauthorized?.()
        return
      }
      if (!res.ok) {
        console.error('stats HTTP', res.status)
        return
      }
      const data: Stats = await res.json()
      if (!data?.system) return
      const nodes = data.resource_nodes ?? []
      const effectiveNode = data.system.node_id || nodeId
      if (nodes.length && !nodes.some(n => n.id === effectiveNode) && effectiveNode !== 'queen') {
        selectNode('queen')
        return
      }
      setStats(prev => {
        if (mode === 'light' && prev) {
          return {
            ...prev,
            system: data.system,
            users: data.users,
            resource_nodes: data.resource_nodes ?? prev.resource_nodes,
          }
        }
        return data
      })
      const t = new Date().toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      setCpuHistory(prev => [...prev.slice(-19), { t, v: data.system.cpu_percent }])
      setNetHistory(prev => [
        ...prev.slice(-19),
        { t, v: data.system.network_util_percent ?? 0 },
      ])
    } catch (e) {
      console.error(e)
    } finally {
      if (mode === 'full') setLoading(false)
    }
  }, [token, onUnauthorized, nodeId, selectNode])

  useEffect(() => {
    fetchStats('full')
    const interval = setInterval(() => fetchStats('light'), 5000)
    return () => clearInterval(interval)
  }, [fetchStats])

  if (!stats) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <div className="animate-spin w-8 h-8 border-2 border-white border-t-transparent rounded-full" />
        <p className="text-[#666] text-sm">Загрузка статистики...</p>
      </div>
    )
  }

  const sys = stats.system
  const cores = sys.cpu_cores
  const cpuLabel = cores
    ? `CPU — ${sys.cpu_percent.toFixed(1)}% · ${cores} ядер`
    : `CPU — ${sys.cpu_percent.toFixed(1)}%`
  const unreachable = sys.reachable === false

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Дашборд</h1>
        <button
          onClick={() => fetchStats('full')}
          disabled={loading}
          className="flex items-center gap-2 text-xs text-[#666] hover:text-white transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Обновить
        </button>
      </div>

      {/* User stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard icon={Users} label="Пользователей" value={stats.users.total} />
        <div className="bg-[#111] border border-[#222] rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[#666] text-xs uppercase tracking-wider">Подписки</span>
            <Wifi className="w-4 h-4 text-[#666]" />
          </div>
          <div className="space-y-2.5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[#aaa] text-sm" title="YuMoney / покупка в приложении">Оплаченные</span>
              <span className="text-2xl font-bold tabular-nums">{stats.users.subscriptions_paid ?? 0}</span>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[#aaa] text-sm" title="Выдал админ или бесплатный бонус (amount=0)">Выданные</span>
              <span className="text-2xl font-bold tabular-nums">{stats.users.subscriptions_granted ?? 0}</span>
            </div>
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[#aaa] text-sm" title="Пробный период (trial)">Пробный период</span>
              <span className="text-2xl font-bold tabular-nums">{stats.users.subscriptions_trial ?? 0}</span>
            </div>
          </div>
          <div className="text-[#555] text-xs mt-3 pt-2 border-t border-[#1e1e1e]">
            всего живых: {stats.users.active_subscriptions}
          </div>
        </div>
        <div className="bg-[#111] border border-[#222] rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[#666] text-xs uppercase tracking-wider">Онлайн</span>
            <div className={`w-2.5 h-2.5 rounded-full ${stats.users.connected_devices > 0 ? 'bg-green-400 shadow-[0_0_6px_#4ade80]' : 'bg-[#444]'}`} />
          </div>
          <div className="text-2xl font-bold">{stats.users.connected_devices}</div>
          <div className="text-[#555] text-xs mt-1">все ноды: Улей + соты</div>
          <div
            className="text-[#555] text-xs mt-1"
            title={
              stats.users.peak_online_at
                ? `Зафиксировано: ${new Date(stats.users.peak_online_at).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })}`
                : undefined
            }
          >
            максимум: {Math.max(stats.users.peak_online_devices ?? 0, stats.users.connected_devices)}
          </div>
        </div>
      </div>

      {/* System */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-[#111] border border-[#222] rounded-xl p-5">
          <div className="flex items-center justify-between gap-3 mb-4">
            <h3 className="text-xs text-[#666] uppercase tracking-wider flex items-center gap-2 shrink-0">
              <Cpu className="w-3.5 h-3.5" /> Системные ресурсы
            </h3>
            <div className="relative min-w-[8.5rem] max-w-[13rem]">
              <Server className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#555] pointer-events-none" />
              <select
                value={resourceNodes.some(n => n.id === nodeId) ? nodeId : 'queen'}
                onChange={e => selectNode(e.target.value)}
                aria-label="Нода"
                className="w-full appearance-none pl-8 pr-7 py-1.5 text-xs bg-[#0a0a0a] border border-[#2a2a2a] rounded-lg text-white focus:outline-none focus:border-[#444] hover:border-[#3a3a3a] cursor-pointer"
                title="Нода для CPU / RAM / канала"
              >
                {resourceNodes.map(n => (
                  <option key={n.id} value={n.id}>
                    {n.title || n.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#555] pointer-events-none" />
            </div>
          </div>
          {unreachable && (
            <div className="text-xs text-amber-500/90 mb-3">Сота сейчас не отвечает — метрики недоступны</div>
          )}
          {(sys.cpu_model || sys.cpu_freq_base_mhz != null || cores != null) && (
            <div className="text-xs text-[#666] mb-3 space-y-1">
              {sys.cpu_freq_base_mhz != null && (
                <div>
                  Частота (номинал):{' '}
                  <span className="text-[#aaa]">{formatGhz(sys.cpu_freq_base_mhz)}</span>
                  {sys.cpu_freq_current_mhz != null && !sys.cpu_freq_estimated && (
                    <span className="ml-3">
                      сейчас:{' '}
                      <span className="text-white font-medium">{formatLiveMhz(sys.cpu_freq_current_mhz)}</span>
                    </span>
                  )}
                </div>
              )}
              <div className="text-[#555] truncate" title={sys.cpu_model || undefined}>
                {sys.cpu_model || 'CPU'}
                {cores != null ? ` · ${cores} ядер` : ''}
              </div>
            </div>
          )}
          <ProgressBar percent={sys.cpu_percent} label={cpuLabel} />
          <ProgressBar
            percent={sys.memory_percent}
            label={`RAM — ${sys.memory_used_gb} / ${sys.memory_total_gb} GB`}
          />
          {sys.disk_percent != null && sys.disk_total_gb != null && (
            <ProgressBar
              percent={sys.disk_percent}
              label={`Диск — ${sys.disk_used_gb} / ${sys.disk_total_gb} GB`}
            />
          )}
          <div className="mt-1 pt-3 border-t border-[#1e1e1e]">
            <div className="flex items-center gap-2 text-xs text-[#666] mb-1">
              <Activity className="w-3.5 h-3.5" />
              <span>
                Канал{sys.network_interface ? ` (${sys.network_interface})` : ''}
                {' · '}
                {formatBandwidth(sys.network_mbps_rx ?? 0)}↓ / {formatBandwidth(sys.network_mbps_tx ?? 0)}↑
                {' · '}
                лимит {sys.network_link_capacity_mbps?.toFixed(0) ?? '1000'} Мбит/с
              </span>
            </div>
            <ProgressBar
              percent={sys.network_util_percent ?? 0}
              label={`Загрузка канала — ${(sys.network_util_percent ?? 0).toFixed(1)}%`}
            />
          </div>
        </div>

        <div className="bg-[#111] border border-[#222] rounded-xl p-5 flex flex-col gap-5">
          <LoadAreaChart
            title="CPU — загрузка (%)"
            data={cpuHistory}
            stroke="#fff"
            fill="#ffffff15"
            seriesLabel="CPU"
          />
          <div className="border-t border-[#1e1e1e] pt-5">
            <LoadAreaChart
              title="Канал — загрузка (%)"
              subtitle={`${formatBandwidth(sys.network_mbps_rx ?? 0)}↓ / ${formatBandwidth(sys.network_mbps_tx ?? 0)}↑`}
              data={netHistory}
              stroke="#38bdf8"
              fill="#38bdf815"
              seriesLabel="Канал"
              emptyHint="Первая точка — 0%. Следующие обновления покажут скорость."
            />
          </div>
        </div>
      </div>

      <VkHashesCard hashes={stats.vk_hashes} vkUsers={stats.vk_users} summary={stats.vk_hash_summary} />
    </div>
  )
}
