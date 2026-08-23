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
  manual_slot?: string | null
  manual_slot_title?: string | null
  last_error: string | null
  has_ssh_password?: boolean
  load?: CellLoad
  capacity?: { max_online: number; mode?: string; bottleneck?: string }
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
        <p className="text-xs text-[#555] mt-1 flex items-center gap-1">
          <Server className="w-3 h-3 shrink-0" />
          характеристики сервера: нет данных
        </p>
      )
    }
    if (cell.status === 'active') {
      return (
        <p className="text-xs text-[#555] mt-1 flex items-center gap-1">
          <Server className="w-3 h-3 shrink-0" />
          характеристики: cell-agent недоступен
        </p>
      )
    }
    return null
  }
  if (!hw) {
    return (
      <p className="text-xs text-[#555] mt-1 flex items-center gap-1">
        <Server className="w-3 h-3 shrink-0" />
        характеристики сервера: обновление…
      </p>
    )
  }
  return (
    <p className="text-sm text-[#bbb] mt-1.5 flex items-center gap-1.5">
      <Server className="w-3.5 h-3.5 text-[#666] shrink-0" />
      {hw}
    </p>
  )
}

function CellLoadGrid({
  cell,
  cpuThreshold,
  memThreshold,
  bwThreshold,
}: {
  cell: HiveCell
  cpuThreshold: number
  memThreshold: number
  bwThreshold: number
}) {
  if (!cell.load) return null
  const { cpu_percent, memory_percent, network_util_percent, network_mbps_rx, network_mbps_tx } = cell.load
  const netRx = network_mbps_rx ?? 0
  const netTx = network_mbps_tx ?? 0
  const netUtil = network_util_percent ?? 0
  const hot = cpu_percent >= cpuThreshold || memory_percent >= memThreshold || netUtil >= bwThreshold
  return (
    <>
    <div className={`grid grid-cols-3 gap-2 mt-3 ${hot ? 'opacity-100' : 'opacity-90'}`}>
      <div className="bg-[#0a0a0a] border border-[#222] rounded-lg px-3 py-2">
        <p className="text-[10px] text-[#666] uppercase flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU</p>
        <p className={`text-lg font-semibold mt-0.5 ${cpu_percent >= cpuThreshold ? 'text-amber-400' : ''}`}>
          {cpu_percent}%
        </p>
      </div>
      <div className="bg-[#0a0a0a] border border-[#222] rounded-lg px-3 py-2">
        <p className="text-[10px] text-[#666] uppercase flex items-center gap-1"><HardDrive className="w-3 h-3" /> RAM</p>
        <p className={`text-lg font-semibold mt-0.5 ${memory_percent >= memThreshold ? 'text-amber-400' : ''}`}>
          {memory_percent}%
        </p>
      </div>
      <div className="bg-[#0a0a0a] border border-[#222] rounded-lg px-3 py-2">
        <p className="text-[10px] text-[#666] uppercase flex items-center gap-1"><Activity className="w-3 h-3" /> Канал</p>
        <p className={`text-lg font-semibold mt-0.5 ${netUtil >= bwThreshold ? 'text-amber-400' : ''}`}>
          {netUtil.toFixed(1)}%
        </p>
        <p className="text-[10px] text-[#555] mt-0.5">{fmtBandwidth(netRx)}↓ {fmtBandwidth(netTx)}↑</p>
      </div>
    </div>
    {typeof cell.load.wg_peers_total === 'number' && (
      <p className="text-[11px] text-[#777] mt-2">
        WG peer’ы: {cell.load.wg_peers_total} · never-hs {cell.load.wg_peers_never_hs ?? 0} · live {cell.load.wg_peers_live_3m ?? 0} (онлайн)
        {typeof cell.load.wg_peers_live_known === 'number' ? ` · свои ${cell.load.wg_peers_live_known}` : ''}
        {(cell.load.wg_gc_last_removed ?? 0) > 0 ? ` · gc −${cell.load.wg_gc_last_removed}` : ''}
      </p>
    )}
    </>
  )
}

const statusLabel: Record<string, string> = {
  active: 'Активна',
  provisioning: 'Настройка…',
  pending: 'Подключение…',
  draining: 'Вывод из эксплуатации',
  offline: 'Выключена',
  error: 'Ошибка',
}

function fmtDetail(d: unknown): string {
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map(fmtDetail).join('; ')
  if (d && typeof d === 'object' && 'msg' in d) return String((d as { msg: string }).msg)
  return 'Ошибка подключения соты'
}

export default function HivePage({ token }: { token: string }) {
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
  const [cells, setCells] = useState<HiveCell[]>([])
  const [summary, setSummary] = useState<HiveSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
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
  }, [token])

  useEffect(() => {
    const t = setInterval(() => { load(true) }, 10000)
    return () => clearInterval(t)
  }, [load])

  useEffect(() => {
    const provisioning = cells.some(c => c.status === 'provisioning')
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
      setSuccess(data.message || `Сота «${data.name}» — настройка запущена`)
      await load()
    } finally {
      setBusy(null)
    }
  }

  const setStatus = async (id: string, status: string) => {
    setBusy(id)
    await fetch(`/api/admin/hive/cells/${id}`, { method: 'PATCH', headers, body: JSON.stringify({ status }) })
    await load()
    setBusy(null)
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

  const queenCell = cells.find(c => c.is_queen)
  const ql = queenCell?.load || summary?.queen_load
  const queenHw = fmtHardware(ql)
  const hiveOnline = cells.reduce((n, c) => n + (c.online_count || 0), 0)

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Hexagon className="w-7 h-7" />
            Улей
          </h1>
          <p className="text-[#888] text-sm mt-1">
            Характеристики и нагрузка — с сервера, обновление каждые 10 с.
            Cell-agent на сотах синхронизируется с Ульем автоматически.
          </p>
        </div>
        <button type="button" onClick={() => { setLoading(true); load() }}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#1a1a1a] text-sm text-[#aaa] hover:text-white">
          <RefreshCw className="w-4 h-4" /> Обновить
        </button>
      </div>
      {metricsAt && (
        <p className="text-xs text-[#555] -mt-3">
          Последнее обновление: {metricsAt.toLocaleTimeString('ru')}
        </p>
      )}

      {summary && ql && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="bg-[#111] border border-[#222] rounded-xl p-4">
            <p className="text-[#666] text-xs uppercase">Онлайн всего</p>
            <p className="text-2xl font-semibold mt-1">{hiveOnline} / {summary.total_capacity_online}</p>
            <p className="text-xs text-[#666] mt-1">
              {cells.filter(c => c.is_queen).reduce((n, c) => n + (c.online_count || 0), 0)} Улей
              {' + '}
              {cells.filter(c => !c.is_queen).reduce((n, c) => n + (c.online_count || 0), 0)} соты
            </p>
          </div>
          <div className="bg-[#111] border border-[#222] rounded-xl p-4">
            <p className="text-[#666] text-xs uppercase flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU Улья</p>
            <p className={`text-2xl font-semibold mt-1 ${ql.cpu_percent >= summary.cpu_threshold ? 'text-amber-400' : ''}`}>
              {ql.cpu_percent}%
            </p>
          </div>
          <div className="bg-[#111] border border-[#222] rounded-xl p-4">
            <p className="text-[#666] text-xs uppercase flex items-center gap-1"><HardDrive className="w-3 h-3" /> RAM Улья</p>
            <p className={`text-2xl font-semibold mt-1 ${ql.memory_percent >= summary.mem_threshold ? 'text-amber-400' : ''}`}>
              {ql.memory_percent}%
            </p>
          </div>
          <div className="bg-[#111] border border-[#222] rounded-xl p-4">
            <p className="text-[#666] text-xs uppercase flex items-center gap-1"><Activity className="w-3 h-3" /> Канал Улья</p>
            <p className={`text-2xl font-semibold mt-1 ${(ql.network_util_percent ?? 0) >= summary.bandwidth_threshold ? 'text-amber-400' : ''}`}>
              {(ql.network_util_percent ?? 0).toFixed(1)}%
            </p>
            <p className="text-xs text-[#555] mt-1">
              {fmtBandwidth(ql.network_mbps_rx ?? 0)}↓ / {fmtBandwidth(ql.network_mbps_tx ?? 0)}↑
            </p>
          </div>
          <div className="bg-[#111] border border-[#222] rounded-xl p-4">
            <p className="text-[#666] text-xs uppercase">Режим</p>
            <p className="text-sm font-medium mt-2">
              {ql.build_running ? (
                <span className="text-blue-400">Сборка OTA — VPN на Улье</span>
              ) : summary.queen_accepting_vpn ? (
                <span className="text-emerald-400">Улей в норме</span>
              ) : (
                <span className="text-orange-400">Улей нагружен</span>
              )}
            </p>
            {summary.all_cells_full && (
              <p className="text-xs text-red-400 mt-2">Все соты заполнены — добавьте новые соты</p>
            )}
          </div>
        </div>
      )}
      {queenHw && (
        <p className="text-sm text-[#aaa] flex items-center gap-1.5 -mt-2">
          <Server className="w-3.5 h-3.5 text-[#666]" />
          Улей: {queenHw}
        </p>
      )}
      {summary && (
        <div className="bg-[#0d0d0d] border border-[#2a2a2a] rounded-lg px-4 py-3 text-xs text-[#888] leading-relaxed">
          <p className="text-[#aaa] font-medium mb-1">Серверы</p>
          <p>
            Клиент сам выбирает Сервер 1 (Улей), 2 или 3 — это отдельные ноды.
            Живой VPN Улей не перекидывает. CPU ≥ {summary.cpu_threshold}%, RAM ≥ {summary.mem_threshold}%,
            канал ≥ {summary.bandwidth_threshold}% — индикатор нагрузки, не авто-баланс.
          </p>
        </div>
      )}

      <HiveAvailabilityPanel token={token} />

      <div className="bg-[#111] border border-[#222] rounded-xl p-4 md:p-5">
        <div className="flex items-center justify-between gap-3 mb-2">
          <div>
            <h2 className="font-medium">Инциденты Улья (ошибки/падения)</h2>
            <p className="text-xs text-[#666] mt-0.5">
              Записи хранятся в базе, пока не нажмёте «Очистить». Не пропадают при обновлении страницы.
            </p>
            {incidentsSeenAt && (
              <p className="text-[11px] text-[#555] mt-1">
                Последний просмотр панели инцидентов: {new Date(incidentsSeenAt).toLocaleString('ru-RU')}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={clearIncidents}
            disabled={busy === 'incidents' || incidents.length === 0}
            className="text-xs px-3 py-1.5 rounded-lg border border-[#333] bg-[#1a1a1a] text-[#ddd] cursor-pointer select-none touch-manipulation transition duration-100 hover:text-white hover:border-[#555] hover:bg-[#222] active:scale-[0.96] active:bg-[#0a0a0a] disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100"
          >
            {busy === 'incidents' ? 'Удаляю…' : 'Очистить'}
          </button>
        </div>
        {incidents.length === 0 ? (
          <p className="text-xs text-[#666]">Инцидентов пока нет.</p>
        ) : (
          <div className="max-h-72 overflow-auto space-y-2 pr-1">
            {incidents.map((it, idx) => (
              <div key={`${it.ts}-${idx}`} className="bg-[#0a0a0a] border border-[#242424] rounded-lg px-3 py-2">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className={`${it.severity === 'error' ? 'text-red-400' : 'text-amber-300'} uppercase`}>
                    {it.severity}
                  </span>
                  <span className="text-[#888]">{new Date(it.ts).toLocaleString('ru-RU')}</span>
                  <span className="text-violet-300">{it.category}</span>
                  <span className="text-[#777]">{it.source}</span>
                  {(it.cell_name || it.cell_ip) && (
                    <span className="text-[#999]">
                      {it.cell_name || 'Сота'}{it.cell_ip ? ` (${it.cell_ip})` : ''}
                    </span>
                  )}
                </div>
                <p className="text-sm text-[#ddd] mt-1">{it.message}</p>
                <p className="text-xs text-amber-300 mt-1">{it.hint}</p>
                {it.checks && it.checks.length > 0 && (
                  <p className="text-xs text-[#777] mt-1">{it.checks.join(' · ')}</p>
                )}
                {it.details && <p className="text-xs text-[#666] mt-1 break-all">{it.details}</p>}
              </div>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-800 text-red-300 text-sm rounded-lg px-4 py-3 whitespace-pre-wrap">{error}</div>
      )}
      {success && (
        <div className="bg-emerald-950/40 border border-emerald-800 text-emerald-300 text-sm rounded-lg px-4 py-3">{success}</div>
      )}

      <div className="bg-[#111] border border-[#222] rounded-xl p-4 md:p-6">
        <h2 className="font-medium mb-1">Добавить соту</h2>
        <p className="text-xs text-[#666] mb-4">IP + root-пароль SSH. Ubuntu/Debian, порт 22 открыт. 1–3 мин.</p>
        <form onSubmit={connectAuto} className="grid gap-3 md:grid-cols-2">
          <input required placeholder="IP сервера" value={form.host}
            onChange={e => setForm(f => ({ ...f, host: e.target.value }))}
            className="bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-sm font-mono" />
          <input required type="password" placeholder="SSH пароль root" value={form.password}
            onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
            className="bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-sm" />
          <input placeholder="Название (необязательно)" value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            className="md:col-span-2 bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-sm" />
          <button type="submit" disabled={busy === 'auto'}
            className="md:col-span-2 flex items-center justify-center gap-2 bg-white text-black rounded-lg py-2.5 text-sm font-medium disabled:opacity-50">
            {busy === 'auto' ? <><Loader2 className="w-4 h-4 animate-spin" /> Настраиваем…</> : <><Plus className="w-4 h-4" /> Подключить соту</>}
          </button>
        </form>
      </div>

      {loading ? <p className="text-[#666] text-sm">Загрузка…</p> : (
        <div className="space-y-3">
          {cells.map(cell => (
            <div key={cell.id} className="bg-[#111] border border-[#222] rounded-xl p-4 md:p-5">
              <div className="flex flex-col md:flex-row md:justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    {cell.is_queen ? <Crown className="w-4 h-4 text-amber-400" /> :
                      cell.status === 'active' ? <Wifi className="w-4 h-4 text-emerald-400" /> :
                      cell.status === 'provisioning' ? <Loader2 className="w-4 h-4 text-blue-400 animate-spin" /> :
                      <WifiOff className="w-4 h-4 text-[#555]" />}
                    <h2 className="font-semibold">{cell.name}</h2>
                    {cell.manual_slot_title && (
                      <span className="text-xs bg-[#1a1a1a] text-[#ccc] border border-[#333] px-2 py-0.5 rounded">
                        {cell.manual_slot_title}
                      </span>
                    )}
                    {cell.is_queen && <span className="text-xs bg-amber-950 text-amber-300 px-2 py-0.5 rounded">Улей</span>}
                    <span className="text-xs text-[#888]">{statusLabel[cell.status] || cell.status}</span>
                  </div>
                  <p className="text-sm text-[#888] mt-1 font-mono">{cell.public_ip}:{cell.wdtt_port}</p>
                  {!cell.is_queen && cell.status === 'active' && !cell.has_ssh_password && (
                    <p className="text-xs text-amber-500 mt-0.5">
                      SSH не сохранён — автообновление агента недоступно (переподключите соту)
                    </p>
                  )}
                  <CellHardwareLine cell={cell} />
                  {summary && (
                    <CellLoadGrid
                      cell={cell}
                      cpuThreshold={summary.cpu_threshold}
                      memThreshold={summary.mem_threshold}
                      bwThreshold={summary.bandwidth_threshold}
                    />
                  )}
                  {cell.assigned_devices > cell.online_count && !cell.is_queen && (
                    <p className="text-xs text-[#666] mt-1">
                      привязано в БД: {cell.assigned_devices}
                      {cell.assigned_devices > cell.online_count
                        ? ` (офлайн ${cell.assigned_devices - cell.online_count})`
                        : ''}
                    </p>
                  )}
                  <p className={`text-xs mt-1 ${cell.online_count >= cell.max_online ? 'text-red-400' : 'text-[#666]'}`}>
                    онлайн лимит: {cell.online_count} / {cell.max_online}
                    {cell.capacity?.mode && (
                      <span className="text-[#555]"> · {capModeLabel[cell.capacity.mode] || cell.capacity.mode}</span>
                    )}
                  </p>
                  {cell.last_error && <p className="text-xs text-red-400 mt-2 whitespace-pre-wrap">{cell.last_error}</p>}
                </div>
                <div className="text-right">
                  <p className="text-lg font-semibold">{cell.online_count}</p>
                  <p className="text-xs text-[#666]">{cell.is_queen ? 'онлайн на Улье' : 'онлайн на соте'}</p>
                  {cell.manual_slot_title && cell.online_count > 0 && (
                    <p className="text-[10px] text-emerald-400 mt-0.5">{cell.is_queen ? 'Улей' : (cell.name || cell.manual_slot_title)}</p>
                  )}
                </div>
              </div>
              {!cell.is_queen && (
                <div className="flex gap-2 mt-4 flex-wrap items-center">
                  {cell.status === 'provisioning' && (
                    <span className="text-xs text-blue-400 flex items-center gap-1">
                      <Loader2 className="w-3 h-3 animate-spin" /> Настройка 1–3 мин…
                    </span>
                  )}
                  {cell.status === 'active' && (
                    <button type="button" disabled={busy === cell.id} onClick={() => setStatus(cell.id, 'draining')}
                      title="Сота перестанет принимать новых клиентов. Текущие VPN доработают до отключения — после этого соту можно удалить."
                      className="text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-orange-400 disabled:opacity-50">
                      Вывод
                    </button>
                  )}
                  {cell.status === 'draining' && (
                    <button type="button" disabled={busy === cell.id} onClick={() => setStatus(cell.id, 'active')}
                      className="text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-emerald-400 disabled:opacity-50">
                      Вернуть в работу
                    </button>
                  )}
                  <button type="button" disabled={busy === cell.id} onClick={() => removeCell(cell)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-red-400 flex items-center gap-1 disabled:opacity-50">
                    {busy === cell.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                    {cell.status === 'provisioning' ? 'Отменить' : 'Удалить'}
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
