import { useCallback, useEffect, useRef, useState } from 'react'
import { Hexagon, Plus, Trash2, Wifi, WifiOff, Crown, Loader2, Cpu, HardDrive, Activity, Server } from 'lucide-react'
import HiveAvailabilityPanel from '../components/HiveAvailabilityPanel'
import { bumpIncidentGen, shouldApplyIncidentList } from '../incidentListGuard'
import { mergeHiveCellLoads } from '../hiveCellLoads'

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
          <p className="text-[#666]">Гео</p>
          <p className="text-[#ddd]">{[geo.country, geo.city].filter(Boolean).join(', ') || '—'}</p>
        </div>
        <div>
          <p className="text-[#666]">ASN</p>
          <p className="text-[#ddd] truncate" title={geo.asn}>{geo.asn || '—'}</p>
        </div>
        <div>
          <p className="text-[#666]">Cloudflare loc</p>
          <p className="text-[#ddd]">{trace.loc || '—'}{trace.warp && trace.warp !== 'off' ? ` · warp ${trace.warp}` : ''}</p>
        </div>
        <div>
          <p className="text-[#666]">Резолвер ноды</p>
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
  const [form, setForm] = useState({ host: '', password: '', name: '' })
  const [incidents, setIncidents] = useState<HiveIncident[]>([])
  const [incidentsSeenAt, setIncidentsSeenAt] = useState<string | null>(null)
  const incidentsGen = useRef(0)
  const loadMisses = useRef<Record<string, number>>({})

  const load = useCallback(async (silent = false) => {
    if (!silent) setError(null)
    const gen = incidentsGen.current
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
    const incoming = await cellsRes.json()
    setCells(prev => {
      const merged = mergeHiveCellLoads(prev, Array.isArray(incoming) ? incoming : [], loadMisses.current)
      loadMisses.current = merged.misses
      return merged.cells
    })
    if (sumRes.ok) setSummary(await sumRes.json())
    if (incidentsRes.ok && shouldApplyIncidentList(gen, incidentsGen.current)) {
      const data = await incidentsRes.json().catch(() => ({}))
      setIncidents(Array.isArray(data.items) ? data.items : [])
      setIncidentsSeenAt(typeof data.last_seen_at === 'string' ? data.last_seen_at : null)
    }
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

  const setAdminOnly = async (id: string, adminOnly: boolean) => {
    setBusy(id)
    await fetch(`/api/admin/hive/cells/${id}`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify({ admin_only: adminOnly }),
    })
    await load()
    setBusy(null)
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
    incidentsGen.current = bumpIncidentGen(incidentsGen.current)
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
      incidentsGen.current = bumpIncidentGen(incidentsGen.current)
      const gen = incidentsGen.current
      const listRes = await fetch('/api/admin/hive/incidents?limit=120', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!shouldApplyIncidentList(gen, incidentsGen.current)) return
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

  return (
    <div className="space-y-6 max-w-5xl">
      <h1 className="text-2xl font-bold flex items-center gap-2">
        <Hexagon className="w-7 h-7" />
        Улей
      </h1>
      {queenHw && (
        <p className="text-sm text-[#aaa] flex items-center gap-1.5">
          <Server className="w-3.5 h-3.5 text-[#666]" />
          Улей: {queenHw}
        </p>
      )}

      <HiveAvailabilityPanel
        token={token}
        onlineByHost={Object.fromEntries(cells.map(c => [c.public_ip, c.online_count]))}
      />

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
                    {cell.admin_only && (
                      <span className="text-xs bg-violet-950 text-violet-300 px-2 py-0.5 rounded">Только админ</span>
                    )}
                    {cell.ai_exit && (
                      <span className="text-xs bg-sky-950 text-sky-300 px-2 py-0.5 rounded">Для ИИ</span>
                    )}
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
                  <p className={`text-xs mt-1 ${cell.online_count >= cell.max_online ? 'text-red-400' : 'text-[#666]'}`}>
                    онлайн лимит: {cell.online_count} / {cell.max_online}
                    {cell.capacity?.mode && (
                      <span className="text-[#555]"> · {capModeLabel[cell.capacity.mode] || cell.capacity.mode}</span>
                    )}
                  </p>
                  {cell.last_error && (
                    <p
                      className={`text-xs mt-2 whitespace-pre-wrap ${
                        cell.last_error.startsWith('Профиль для ИИ: настройка') ||
                        cell.last_error.startsWith('Профиль для ИИ: откат')
                          ? 'text-sky-400'
                          : 'text-red-400'
                      }`}
                    >
                      {cell.last_error}
                    </p>
                  )}
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
                  <button
                    type="button"
                    disabled={busy === cell.id}
                    onClick={() => setAdminOnly(cell.id, !cell.admin_only)}
                    title="В меню клиентов и в автобалансе — только для администратора"
                    className={`text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] disabled:opacity-50 ${
                      cell.admin_only ? 'text-violet-300' : 'text-[#aaa]'
                    }`}
                  >
                    {cell.admin_only ? 'Открыть всем' : 'Только админ'}
                  </button>
                  <button
                    type="button"
                    disabled={busy === cell.id || (cell.status !== 'active' && cell.status !== 'draining')}
                    onClick={() => setAiExit(cell.id, !cell.ai_exit)}
                    title="Включить или снять профиль для ИИ на этой соте: гигиена + свой DNS (без WARP). Нужен сохранённый SSH."
                    className={`text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] disabled:opacity-50 ${
                      cell.ai_exit ? 'text-sky-300' : 'text-[#aaa]'
                    }`}
                  >
                    {cell.ai_exit ? 'Снять профиль для ИИ' : 'Профиль для ИИ'}
                  </button>
                  <button
                    type="button"
                    disabled={egressBusy === cell.id || cell.status !== 'active'}
                    onClick={() => checkEgress(cell)}
                    title="Как IP соты видят снаружи: гео, hosting/proxy, PTR, резолвер, ответы ИИ-сайтов"
                    className="text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-[#aaa] flex items-center gap-1 disabled:opacity-50"
                  >
                    {egressBusy === cell.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" />}
                    Проверить IP
                  </button>
                  <button type="button" disabled={busy === cell.id} onClick={() => removeCell(cell)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-red-400 flex items-center gap-1 disabled:opacity-50">
                    {busy === cell.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                    {cell.status === 'provisioning' ? 'Отменить' : 'Удалить'}
                  </button>
                </div>
              )}
              {egress[cell.id] && <EgressCard info={egress[cell.id]} />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
