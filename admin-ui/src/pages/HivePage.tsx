import { useCallback, useEffect, useState } from 'react'
import { Hexagon, Plus, RefreshCw, Trash2, Wifi, WifiOff, Crown, Loader2, Cpu, HardDrive, Activity, Server } from 'lucide-react'
import HiveAvailabilityPanel from '../components/HiveAvailabilityPanel'

interface CellLoad {
  cpu_percent: number
  memory_percent: number
  network_util_percent?: number
  network_mbps_rx?: number
  network_mbps_tx?: number
  network_link_capacity_mbps?: number | null
  network_interface?: string | null
  cpu_cores?: number | null
  memory_total_gb?: number | null
  build_running?: boolean
  vpn_overloaded?: boolean
  wdtt_active?: boolean
  wg_peers_total?: number
  wg_peers_never_hs?: number
  wg_peers_live_3m?: number
  wg_peers_live_known?: number
  wg_gc_last_removed?: number
}

interface HiveCell {
  id: string
  name: string
  is_queen: boolean
  public_ip: string
  wdtt_port: number
  wg_port: number
  max_online: number
  max_clients?: number
  online_count: number
  total_online_count?: number
  assigned_devices: number
  status: string
  accepts_wdtt?: boolean
  admin_only?: boolean
  ai_exit?: boolean
  manual_slot?: string | null
  manual_slot_title?: string | null
  last_error: string | null
  has_ssh_password?: boolean
  load?: CellLoad
  capacity?: { max_online: number; mode?: string; bottleneck?: string }
}

interface EgressInfo {
  cell_ip?: string
  ptr?: string
  geo?: {
    country?: string
    city?: string
    asn?: string
    isp?: string
    reverse?: string
    hosting?: boolean
    proxy?: boolean
  }
  cf_trace?: Record<string, string>
  services?: { name: string; url: string; status: number; latency_ms: number; ok: boolean }[]
  local?: {
    resolvers?: string[]
    units?: Record<string, string>
    proxy_enabled?: boolean
    tproxy_hook?: boolean
    dns_dnat?: boolean
    agent_port_public?: boolean
  }
  checked_at?: string
  error?: string
}

const egressServiceLabel: Record<string, string> = {
  chatgpt: 'ChatGPT',
  gemini: 'Gemini',
  claude: 'Claude',
  openai_api: 'OpenAI API',
}

const capModeLabel: Record<string, string> = {
  live: 'живой расчёт',
  'adaptive+live': 'история + сейчас',
  adaptive: 'по истории',
  fallback: 'оценка по железу',
  estimated: 'оценка',
  manual_cap: 'ручной потолок',
}

interface HiveSummary {
  cells_total: number
  cells_active: number
  total_online_vpn: number
  total_online_all?: number
  worker_cells: number
  queen_accepting_vpn: boolean
  queen_load: CellLoad
  cpu_threshold: number
  mem_threshold: number
  bandwidth_threshold: number
  total_capacity_online: number
  all_cells_full: boolean
  full_cells: number
  rebalanced_moved: number
  rebalanced_blocked: number
  rebalanced_hardware?: number
  rebalanced_returned?: number
}

interface HiveIncident {
  ts: string
  severity: string
  source: string
  cell_name?: string | null
  cell_ip?: string | null
  category: string
  hint: string
  message: string
  details?: string
  checks?: string[]
}

function fmtBandwidth(mbps: number): string {
  if (mbps >= 1) return `${mbps.toFixed(1)} Мбит/с`
  if (mbps >= 0.001) return `${(mbps * 1000).toFixed(0)} Кбит/с`
  return '0'
}

function fmtLinkGbps(mbps: number): string {
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(0)} Гбит/с`
  return `${mbps.toFixed(0)} Мбит/с`
}

/** Характеристики железа — только то, что отдаёт сервер (host / cell-agent). */
function fmtHardware(load?: CellLoad): string {
  if (!load) return ''
  const parts: string[] = []
  if (load.cpu_cores) parts.push(`${load.cpu_cores} ядер`)
  if (load.memory_total_gb) parts.push(`${load.memory_total_gb} ГБ RAM`)
  if (load.network_link_capacity_mbps && load.network_link_capacity_mbps > 0) {
    parts.push(`канал ${fmtLinkGbps(load.network_link_capacity_mbps)}`)
  }
  return parts.join(' · ')
}

function CellHardwareLine({ cell }: { cell: HiveCell }) {
  const hw = fmtHardware(cell.load)
  if (!cell.load) {
    if (cell.is_queen) {
      return (
        <p className="text-xs text-[#888] mt-1 flex items-center gap-1">
          <Server className="w-3 h-3 shrink-0" />
          характеристики сервера: нет данных
        </p>
      )
    }
    if (cell.status === 'active') {
      return (
        <p className="text-xs text-[#888] mt-1 flex items-center gap-1">
          <Server className="w-3 h-3 shrink-0" />
          характеристики: cell-agent недоступен
        </p>
      )
    }
    return null
  }
  if (!hw) {
    return (
      <p className="text-xs text-[#888] mt-1 flex items-center gap-1">
        <Server className="w-3 h-3 shrink-0" />
        характеристики сервера: обновление…
      </p>
    )
  }
  return (
    <p className="text-sm text-[#bbb] mt-1.5 flex items-center gap-1.5">
      <Server className="w-3.5 h-3.5 text-[#888] shrink-0" />
      {hw}
    </p>
  )
}

function CellLoadGrid({ cell, cpuThreshold, memThreshold, bwThreshold }: {
  cell: HiveCell; cpuThreshold: number; memThreshold: number; bwThreshold: number
}) {
  if (!cell.load) return <p className="text-xs text-amber-300 mt-3">Нет данных о нагрузке</p>
  const load = cell.load
  return (
    <div className="flex flex-wrap gap-x-5 gap-y-2 mt-3 text-xs text-[#aaa] tabular-nums">
      <span className={`flex items-center gap-1.5 ${load.cpu_percent >= cpuThreshold ? 'text-amber-300' : ''}`}>
        <Cpu className="w-3.5 h-3.5" /> CPU {load.cpu_percent}%
      </span>
      <span className={`flex items-center gap-1.5 ${load.memory_percent >= memThreshold ? 'text-amber-300' : ''}`}>
        <HardDrive className="w-3.5 h-3.5" /> RAM {load.memory_percent}%
      </span>
      <span className={`flex items-center gap-1.5 ${(load.network_util_percent ?? 0) >= bwThreshold ? 'text-amber-300' : ''}`}>
        <Activity className="w-3.5 h-3.5" /> Канал {(load.network_util_percent ?? 0).toFixed(1)}%
      </span>
    </div>
  )
}

const statusLabel: Record<string, string> = {
  active: 'Активна',
  provisioning: 'Настройка…',
  pending: 'Подключение…',
  draining: 'Не принимает новых',
  offline: 'Выключена',
  error: 'Ошибка',
}

function fmtDetail(d: unknown): string {
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map(fmtDetail).join('; ')
  if (d && typeof d === 'object' && 'msg' in d) return String((d as { msg: string }).msg)
  return 'Ошибка подключения соты'
}

function EgressChip({ ok, label, hint }: { ok: boolean; label: string; hint?: string }) {
  return (
    <span
      title={hint}
      className={`text-[11px] px-2 py-0.5 rounded border ${
        ok ? 'bg-emerald-950/60 text-emerald-300 border-emerald-900' : 'bg-red-950/60 text-red-300 border-red-900'
      }`}
    >
      {label}
    </span>
  )
}

function EgressCard({ info }: { info: EgressInfo }) {
  if (info.error) {
    return (
      <div className="mt-4 border border-red-900/60 bg-red-950/20 rounded-lg p-3">
        <p className="text-xs text-red-300">Проверка выхода не прошла: {info.error}</p>
      </div>
    )
  }
  const geo = info.geo || {}
  const local = info.local || {}
  const trace = info.cf_trace || {}
  return (
    <div className="mt-4 border border-[#222] bg-[#0d0d0d] rounded-lg p-3 space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs text-[#888]">
          Чистота выхода · {info.cell_ip}
          {info.checked_at ? ` · ${info.checked_at}` : ''}
        </p>
        <div className="flex gap-1.5 flex-wrap">
          <EgressChip ok={!geo.hosting} label={geo.hosting ? 'hosting: да' : 'hosting: нет'} hint="Флаг датацентра у ip-api" />
          <EgressChip ok={!geo.proxy} label={geo.proxy ? 'proxy: да' : 'proxy: нет'} hint="Флаг прокси/VPN у ip-api" />
          <EgressChip ok={!!info.ptr} label={info.ptr ? 'PTR есть' : 'PTR пустой'} hint={info.ptr || 'rDNS правится в панели хостера'} />
          <EgressChip
            ok={!local.agent_port_public}
            label={local.agent_port_public ? 'агент открыт' : 'агент закрыт'}
            hint="Порт cell-agent виден интернету — признак VPN-узла"
          />
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <div>
          <p className="text-[#888]">Гео</p>
          <p className="text-[#ddd]">{[geo.country, geo.city].filter(Boolean).join(', ') || '—'}</p>
        </div>
        <div>
          <p className="text-[#888]">ASN</p>
          <p className="text-[#ddd] truncate" title={geo.asn}>{geo.asn || '—'}</p>
        </div>
        <div>
          <p className="text-[#888]">Cloudflare loc</p>
          <p className="text-[#ddd]">{trace.loc || '—'}{trace.warp && trace.warp !== 'off' ? ` · warp ${trace.warp}` : ''}</p>
        </div>
        <div>
          <p className="text-[#888]">Резолвер ноды</p>
          <p className="text-[#ddd] font-mono">{(local.resolvers || []).join(', ') || '—'}</p>
        </div>
      </div>
      {info.services && info.services.length > 0 && (
        <div className="flex gap-1.5 flex-wrap">
          {info.services.map(s => (
            <EgressChip
              key={s.name}
              ok={s.ok}
              label={`${egressServiceLabel[s.name] || s.name}: ${s.status || 'нет ответа'}`}
              hint={`${s.url} · ${s.latency_ms} мс`}
            />
          ))}
        </div>
      )}
      <div className="flex gap-1.5 flex-wrap text-[11px] text-[#777]">
        <span>DNS-заворот: {local.dns_dnat ? 'да' : 'нет'}</span>
        <span>·</span>
        <span>прокси: {local.proxy_enabled ? 'включён' : 'выключен'}</span>
        <span>·</span>
        <span>TPROXY-цепочка: {local.tproxy_hook ? 'подключена' : 'снята (fail-open)'}</span>
        {local.units && (
          <>
            <span>·</span>
            <span>
              unbound {local.units.unbound}, dnsmasq {local.units.dnsmasq}, sing-box {local.units.sing_box}, wdtt{' '}
              {local.units.wdtt}
            </span>
          </>
        )}
      </div>
    </div>
  )
}

export default function HivePage({ token }: { token: string }) {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
  const [cells, setCells] = useState<HiveCell[]>([])
  const [summary, setSummary] = useState<HiveSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [egress, setEgress] = useState<Record<string, EgressInfo>>({})
  const [egressBusy, setEgressBusy] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [incidentsOpen, setIncidentsOpen] = useState(false)
  const [form, setForm] = useState({ host: '', password: '', name: '' })
  const [metricsAt, setMetricsAt] = useState<Date | null>(null)
  const [incidents, setIncidents] = useState<HiveIncident[]>([])
  const [incidentsSeenAt, setIncidentsSeenAt] = useState<string | null>(null)

  const load = useCallback(async (silent = false) => {
    if (!silent) setError(null)
    const [cellsRes, sumRes, incidentsRes] = await Promise.all([
      fetch('/api/admin/hive/cells', { headers: { Authorization: `Bearer ${token}` } }),
      fetch('/api/admin/hive/summary', { headers: { Authorization: `Bearer ${token}` } }),
      fetch('/api/admin/hive/incidents?limit=120', { headers: { Authorization: `Bearer ${token}` } }),
    ])
    if (!cellsRes.ok) {
      setError('Не удалось загрузить соты')
      setLoading(false)
      return
    }
    setCells(await cellsRes.json())
    if (sumRes.ok) setSummary(await sumRes.json())
    if (incidentsRes.ok) {
      const data = await incidentsRes.json().catch(() => ({}))
      setIncidents(Array.isArray(data.items) ? data.items : [])
      setIncidentsSeenAt(typeof data.last_seen_at === 'string' ? data.last_seen_at : null)
    }
    setMetricsAt(new Date())
    setLoading(false)
  }, [token])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!incidentsOpen) return
    const markSeen = async () => {
      const res = await fetch('/api/admin/hive/incidents/seen', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) return
      const data = await res.json().catch(() => ({}))
      if (typeof data.seen_at === 'string') setIncidentsSeenAt(data.seen_at)
    }
    void markSeen()
  }, [token, incidentsOpen])

  useEffect(() => {
    const t = setInterval(() => { load(true) }, 10000)
    return () => clearInterval(t)
  }, [load])

  useEffect(() => {
    const provisioning = cells.some(
      c =>
        c.status === 'provisioning' ||
        (c.last_error || '').startsWith('Профиль для ИИ: настройка') ||
        (c.last_error || '').startsWith('Профиль для ИИ: откат'),
    )
    if (!provisioning) return
    const t = setInterval(() => { load(true) }, 4000)
    return () => clearInterval(t)
  }, [cells, load])

  const connectAuto = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy('auto')
    setError(null)
    setSuccess(null)
    try {
      const body: Record<string, string> = {
        host: form.host.trim(),
        password: form.password,
      }
      if (form.name.trim()) body.name = form.name.trim()

      const res = await fetch('/api/admin/hive/cells/auto', {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(fmtDetail(data.detail))
        return
      }
      setForm({ host: '', password: '', name: '' })
      setAddOpen(false)
      setSuccess(data.message || `Сота «${data.name}» — настройка запущена`)
      await load()
    } finally {
      setBusy(null)
    }
  }

  const updateCell = async (id: string, patch: { status?: string; admin_only?: boolean }) => {
    setBusy(id)
    setError(null)
    try {
      const res = await fetch(`/api/admin/hive/cells/${id}`, { method: 'PATCH', headers, body: JSON.stringify(patch) })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(fmtDetail(data.detail))
        return
      }
      await load()
    } catch {
      setError('Не удалось сохранить настройки соты')
    } finally {
      setBusy(null)
    }
  }

  const setStatus = (id: string, status: string) => updateCell(id, { status })

  const setAdminOnly = async (id: string, adminOnly: boolean) => {
    await updateCell(id, { admin_only: adminOnly })
  }

  const setAiExit = async (id: string, aiExit: boolean) => {
    const cell = cells.find(c => c.id === id)
    if (!cell) return
    if (!cell.has_ssh_password) {
      setError('Нужен сохранённый SSH — переподключите соту через автоподключение')
      return
    }
    const ok = aiExit
      ? confirm(
          `Включить «Профиль для ИИ» на «${cell.name}»?\n\n` +
            'На соте сами поставятся гигиена (9100 только Улью) и свой DNS. ' +
            'WARP/прокси не включаем. Займёт 1–2 минуты, VPN не рестартуем.',
        )
      : confirm(
          `Снять «Профиль для ИИ» с «${cell.name}»?\n\n` +
            'Откатим DNS/прокси и снова откроем 9100 наружу (как у обычной соты). 1–2 минуты.',
        )
    if (!ok) return
    setBusy(id)
    setError(null)
    try {
      const res = await fetch(`/api/admin/hive/cells/${id}`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ ai_exit: aiExit }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(fmtDetail(data.detail) || `HTTP ${res.status}`)
        return
      }
      if (data.message) setSuccess(data.message)
      await load()
    } finally {
      setBusy(null)
    }
  }

  const checkEgress = async (cell: HiveCell) => {
    setEgressBusy(cell.id)
    try {
      const res = await fetch(`/api/admin/hive/cells/${cell.id}/egress-check`, { method: 'POST', headers })
      const data = await res.json().catch(() => ({}))
      setEgress(prev => ({
        ...prev,
        [cell.id]: res.ok
          ? { ...data, checked_at: new Date().toLocaleTimeString('ru-RU') }
          : { error: fmtDetail(data.detail) || `HTTP ${res.status}` },
      }))
    } finally {
      setEgressBusy(null)
    }
  }

  const removeCell = async (cell: HiveCell) => {
    if (cell.is_queen) return
    const force = cell.status === 'provisioning' || cell.status === 'error' || cell.status === 'pending'
    const msg = force
      ? `Удалить соту «${cell.name}»? (настройка будет прервана)`
      : `Удалить соту «${cell.name}»?`
    if (!confirm(msg)) return
    setBusy(cell.id)
    try {
      const q = force ? '?force=true' : ''
      const res = await fetch(`/api/admin/hive/cells/${cell.id}${q}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) setError(fmtDetail(body.detail))
      else setSuccess(`Сота «${cell.name}» удалена`)
      await load()
    } finally {
      setBusy(null)
    }
  }

  const clearIncidents = async () => {
    if (busy === 'incidents') return
    setBusy('incidents')
    setError(null)
    setIncidents([])
    try {
      const res = await fetch('/api/admin/hive/incidents/clear', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        setError('Не удалось очистить инциденты')
        await load(true)
        return
      }
      const listRes = await fetch('/api/admin/hive/incidents?limit=120', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (listRes.ok) {
        const data = await listRes.json().catch(() => ({}))
        setIncidents(Array.isArray(data.items) ? data.items : [])
      }
    } catch {
      setError('Не удалось очистить инциденты')
      await load(true)
    } finally {
      setBusy(null)
    }
  }

  const hiveOnline = cells.reduce((n, c) => n + (c.online_count || 0), 0)
  const activeCells = cells.filter(c => c.status === 'active').length
  const actionClass = 'text-xs px-3 py-2 rounded-lg border border-[#333] bg-[#1a1a1a] hover:bg-[#222] disabled:opacity-50'

  return (
    <div className="space-y-5 max-w-5xl min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold flex items-center gap-2"><Hexagon className="w-7 h-7" /> Улей</h1>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => { void load() }} aria-label="Обновить серверы"
            className="p-2.5 rounded-lg border border-[#333] text-[#aaa] hover:text-white hover:bg-[#1a1a1a]">
            <RefreshCw className="w-4 h-4" />
          </button>
          <button type="button" onClick={() => setAddOpen(v => !v)} aria-expanded={addOpen} aria-controls="add-cell"
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-white text-black text-sm font-medium">
            <Plus className="w-4 h-4" /> Добавить соту
          </button>
        </div>
      </div>

      {error && <div role="alert" className="bg-red-950/40 border border-red-800 text-red-300 text-sm rounded-lg px-4 py-3 whitespace-pre-wrap">{error}</div>}
      {success && <div role="status" className="bg-emerald-950/40 border border-emerald-800 text-emerald-300 text-sm rounded-lg px-4 py-3">{success}</div>}

      {addOpen && (
        <div id="add-cell" className="bg-[#111] border border-[#222] rounded-xl p-4 md:p-5">
          <div className="flex justify-between items-center gap-3 mb-4">
            <h2 className="font-medium">Новая сота</h2>
            <button type="button" onClick={() => setAddOpen(false)} className="text-sm text-[#aaa] hover:text-white">Закрыть</button>
          </div>
          <form onSubmit={connectAuto} className="grid gap-3 md:grid-cols-2">
            <label className="text-xs text-[#aaa] space-y-1.5">IP сервера
              <input required value={form.host} autoComplete="off"
                onChange={e => setForm(f => ({ ...f, host: e.target.value }))}
                className="block w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-sm text-white font-mono" />
            </label>
            <label className="text-xs text-[#aaa] space-y-1.5">SSH пароль root
              <input required type="password" value={form.password} autoComplete="new-password"
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                className="block w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-sm text-white" />
            </label>
            <label className="md:col-span-2 text-xs text-[#aaa] space-y-1.5">Название <span className="text-[#888]">(необязательно)</span>
              <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                className="block w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-sm text-white" />
            </label>
            <p className="md:col-span-2 text-xs text-[#888]">Ubuntu / Debian · SSH порт 22</p>
            <button type="submit" disabled={busy === 'auto'}
              className="md:col-span-2 flex items-center justify-center gap-2 bg-white text-black rounded-lg py-2.5 text-sm font-medium disabled:opacity-50">
              {busy === 'auto' ? <><Loader2 className="w-4 h-4 animate-spin" /> Настраиваем…</> : 'Подключить соту'}
            </button>
          </form>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 bg-[#111] border border-[#222] rounded-xl px-4 py-3 text-sm">
        <p><span className="text-[#888]">Онлайн</span> <strong className="ml-2 tabular-nums">{loading ? '…' : hiveOnline}</strong></p>
        <p><span className="text-[#888]">Серверы в работе</span> <strong className="ml-2 tabular-nums">{loading ? '…' : `${activeCells} / ${cells.length}`}</strong></p>
        {metricsAt && <span className="sm:ml-auto text-xs text-[#888]">Обновлено {metricsAt.toLocaleTimeString('ru')}</span>}
      </div>
      {summary?.all_cells_full && <p role="status" className="text-sm text-amber-300">Соты заполнены — добавьте сервер.</p>}
      {summary?.queen_load?.build_running && <p className="text-sm text-blue-300">На Улье идёт сборка обновления.</p>}

      {loading ? <p className="text-[#888] text-sm">Загрузка серверов…</p> : cells.length === 0 ? (
        <p className="text-sm text-[#aaa]">Серверов пока нет. Добавьте первую соту.</p>
      ) : (
        <div className="space-y-3">
          {cells.map(cell => (
            <article key={cell.id} aria-label={cell.name} className="bg-[#111] border border-[#222] rounded-xl p-4 md:p-5 min-w-0">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="font-medium flex flex-wrap items-center gap-2">
                    {cell.is_queen ? <Crown className="w-4 h-4 text-amber-400 shrink-0" /> : cell.status === 'active' ? <Wifi className="w-4 h-4 text-emerald-400 shrink-0" /> : <WifiOff className="w-4 h-4 text-[#888] shrink-0" />}
                    <span className="break-words">{cell.name}</span>
                    {cell.manual_slot_title && <span className="text-xs text-[#888] font-normal">{cell.manual_slot_title}</span>}
                  </h2>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5 text-xs">
                    <span className={cell.status === 'active' ? 'text-emerald-400' : cell.status === 'error' || cell.status === 'offline' ? 'text-red-400' : 'text-amber-300'}>{statusLabel[cell.status] || cell.status}</span>
                    {cell.admin_only && <span className="text-violet-300">Только админ</span>}
                    {cell.ai_exit && <span className="text-sky-300">Профиль для ИИ</span>}
                  </div>
                  <p className="text-xs text-[#888] font-mono mt-2 break-all">{cell.public_ip}:{cell.wdtt_port}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className={`text-xl font-semibold tabular-nums ${cell.online_count >= cell.max_online ? 'text-amber-300' : ''}`}>{cell.online_count}<span className="text-xs font-normal text-[#888]"> / {cell.max_online}</span></p>
                  <p className="text-xs text-[#888] mt-0.5">онлайн / лимит</p>
                </div>
              </div>
              <CellLoadGrid cell={cell} cpuThreshold={summary?.cpu_threshold ?? 80} memThreshold={summary?.mem_threshold ?? 85} bwThreshold={summary?.bandwidth_threshold ?? 90} />
              {cell.last_error && <p className={`text-xs mt-3 whitespace-pre-wrap break-words ${cell.last_error.startsWith('Профиль для ИИ:') ? 'text-sky-300' : 'text-red-400'}`}>{cell.last_error}</p>}

              <details className="mt-4 border-t border-[#222] pt-3">
                <summary className="text-xs text-[#aaa] cursor-pointer hover:text-white py-1">{cell.is_queen ? 'Характеристики' : 'Настройки и характеристики'}</summary>
                <div className="mt-3 space-y-3">
                  <CellHardwareLine cell={cell} />
                  <p className="text-xs text-[#888]">Назначено устройств: {cell.assigned_devices}{cell.capacity?.mode ? ` · лимит: ${capModeLabel[cell.capacity.mode] || cell.capacity.mode}` : ''}</p>
                  {cell.load && <p className="text-xs text-[#888]">Трафик: ↓ {fmtBandwidth(cell.load.network_mbps_rx ?? 0)} · ↑ {fmtBandwidth(cell.load.network_mbps_tx ?? 0)}</p>}
                  {typeof cell.load?.wg_peers_total === 'number' && <p className="text-xs text-[#888]">WG: {cell.load.wg_peers_total} ключей · {cell.load.wg_peers_live_3m ?? 0} онлайн · {cell.load.wg_peers_never_hs ?? 0} без подключения{typeof cell.load.wg_peers_live_known === 'number' ? ` · свои ${cell.load.wg_peers_live_known}` : ''}{(cell.load.wg_gc_last_removed ?? 0) > 0 ? ` · очищено ${cell.load.wg_gc_last_removed}` : ''}</p>}
                  {!cell.is_queen && (
                    <>
                      {!cell.has_ssh_password && <p className="text-xs text-amber-300">SSH пароль не сохранён. Для профиля ИИ переподключите соту.</p>}
                      <div className="flex flex-wrap gap-2">
                        {cell.status === 'active' && <button type="button" disabled={busy === cell.id} onClick={() => setStatus(cell.id, 'draining')} title="Текущие подключения продолжат работать" className={`${actionClass} text-orange-300`}>Не принимать новых</button>}
                        {cell.status === 'draining' && <button type="button" disabled={busy === cell.id} onClick={() => setStatus(cell.id, 'active')} className={`${actionClass} text-emerald-400`}>Вернуть в работу</button>}
                        <button type="button" disabled={busy === cell.id} onClick={() => setAdminOnly(cell.id, !cell.admin_only)} className={`${actionClass} text-[#ccc]`}>{cell.admin_only ? 'Открыть всем' : 'Только админ'}</button>
                        <button type="button" disabled={busy === cell.id || (cell.status !== 'active' && cell.status !== 'draining')} onClick={() => setAiExit(cell.id, !cell.ai_exit)} className={`${actionClass} text-[#ccc]`}>{cell.ai_exit ? 'Снять профиль для ИИ' : 'Профиль для ИИ'}</button>
                        <button type="button" disabled={egressBusy === cell.id || cell.status !== 'active'} onClick={() => checkEgress(cell)} className={`${actionClass} text-[#ccc] flex items-center gap-1.5`}>{egressBusy === cell.id && <Loader2 className="w-3 h-3 animate-spin" />} Проверить IP</button>
                        <button type="button" disabled={busy === cell.id} onClick={() => removeCell(cell)} className={`${actionClass} text-red-400 flex items-center gap-1.5`}><Trash2 className="w-3 h-3" />{cell.status === 'provisioning' ? 'Отменить настройку' : 'Удалить соту'}</button>
                      </div>
                    </>
                  )}
                  {egress[cell.id] && <EgressCard info={egress[cell.id]} />}
                </div>
              </details>
            </article>
          ))}
        </div>
      )}

      <details className="bg-[#111] border border-[#222] rounded-xl">
        <summary className="p-4 text-sm font-medium cursor-pointer hover:text-[#ccc]">Доступность серверов</summary>
        <HiveAvailabilityPanel token={token} />
      </details>
      <details className="bg-[#111] border border-[#222] rounded-xl" onToggle={e => setIncidentsOpen(e.currentTarget.open)}>
        <summary className="p-4 text-sm font-medium cursor-pointer hover:text-[#ccc]">Инциденты <span className={incidents.length ? 'text-amber-300 ml-2' : 'text-[#888] ml-2'}>{incidents.length || 'Нет ошибок'}</span></summary>
        <div className="px-4 pb-4 space-y-3">
          <div className="flex flex-wrap justify-between items-center gap-3">
            <p className="text-xs text-[#888]">{incidentsSeenAt ? `Просмотрено ${new Date(incidentsSeenAt).toLocaleString('ru-RU')}` : 'Журнал событий'}</p>
            <button type="button" onClick={clearIncidents} disabled={busy === 'incidents' || incidents.length === 0} className={`${actionClass} text-[#ccc]`}>{busy === 'incidents' ? 'Удаляю…' : 'Очистить журнал'}</button>
          </div>
          {incidents.length === 0 ? <p className="text-xs text-[#888]">Инцидентов нет.</p> : (
            <div className="max-h-80 overflow-auto space-y-2">
              {incidents.map((it, idx) => (
                <div key={`${it.ts}-${idx}`} className="bg-[#0a0a0a] border border-[#242424] rounded-lg px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-[#888]">
                    <span className={it.severity === 'error' ? 'text-red-400' : 'text-amber-300'}>{it.severity === 'error' ? 'Ошибка' : 'Предупреждение'}</span>
                    <span>{new Date(it.ts).toLocaleString('ru-RU')}</span>
                    {(it.cell_name || it.cell_ip) && <span>{it.cell_name || it.cell_ip}</span>}
                  </div>
                  <p className="text-sm text-[#ddd] mt-1 break-words">{it.message}</p>
                  {it.hint && <p className="text-xs text-amber-300 mt-1">{it.hint}</p>}
                  {(it.details || it.checks?.length) && <details className="mt-2 text-xs text-[#888]"><summary className="cursor-pointer">Подробности</summary><p className="mt-1">{it.category} · {it.source}</p><p className="mt-1">{it.checks?.join(' · ')}</p><p className="mt-1 break-all">{it.details}</p></details>}
                </div>
              ))}
            </div>
          )}
        </div>
      </details>
    </div>
  )
}
