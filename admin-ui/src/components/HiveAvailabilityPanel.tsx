import { useCallback, useEffect, useMemo, useState } from 'react'
import { Radar, ShieldAlert, ShieldCheck, Play, Loader2 } from 'lucide-react'

type Probe = {
  channel: string
  ok: boolean
  latency_ms: number | null
  error_kind: string
  detail: string
  inconclusive: boolean
}

type VantageNode = {
  node: string
  country: string
  city: string
  asn: string
  carrier: string
  ok: boolean
  latency_ms: number | null
  error_kind: string
  detail: string
}

type Vantage = {
  channel: string
  source: string
  total: number
  ok: number
  failed: number
  asked?: number
  ok_ratio: number
  median_latency_ms: number | null
  error_kinds: Record<string, number>
  nodes: VantageNode[]
}

type ClientAgg = {
  window_minutes: number
  reports: number
  failures: number
  by_stage: Record<string, number>
  by_network: Record<string, number>
  by_carrier: Record<string, number>
  by_transport: Record<string, number>
  short_lived_tunnels: number
}

type Target = {
  name: string
  host: string
  role: string
  api_port: number
  wdtt_port: number
  wg_port: number
  domain: string
  ai_exit?: boolean
  status: string
  online_count: number
  note?: string
  local: Record<string, Probe>
  ru: Record<string, Vantage>
  world: Record<string, Vantage>
  peer: Record<string, Probe>
  clients: ClientAgg | null
}

type Verdict = {
  target: string
  host: string
  kind: string
  title: string
  severity: string
  confidence: number
  summary: string
  evidence: string[]
  fixes: string[]
  commands: string[]
  channel: string
}

type PortPlan = {
  action: string
  title: string
  port: number | null
  suggested_port: number | null
  close_port: number | null
  keep_open: number[]
  reason: string
  explain: string
  dead_windows: number
  autoswitch: boolean
  executed: boolean
  candidates: { port: number; ru: string }[]
}

type RelayHop = {
  name: string
  host: string
  ai_exit: boolean
  action: string
  entry: string | null
  exit: string
  reason: string
  explain: string
}

type RelayPlan = {
  action: string
  title: string
  explain: string
  executed: boolean
  hops: RelayHop[]
}

type Report = {
  ts: string
  status: string
  summary: string
  duration_sec: number
  worst_severity: string
  warnings: string[]
  vantage: { ru_nodes?: string[]; world_nodes?: string[]; checks?: number }
  verdicts: Verdict[]
  targets: Target[]
  port_plan?: PortPlan | null
  relay_plan?: RelayPlan | null
}

type AgentSettings = {
  enabled: boolean
  external_enabled: boolean
  interval_sec: number
  ru_nodes: number
  world_nodes: number
  last_run: string | null
  last_status: string | null
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  ok: { label: 'Доступно из РФ', cls: 'text-emerald-400 border-emerald-800 bg-emerald-950/40' },
  degraded: { label: 'Деградация', cls: 'text-amber-300 border-amber-800 bg-amber-950/40' },
  blocked: { label: 'Есть блокировка', cls: 'text-red-400 border-red-800 bg-red-950/40' },
  down: { label: 'Сервис не отвечает', cls: 'text-red-400 border-red-800 bg-red-950/40' },
  unknown: { label: 'Данных мало', cls: 'text-[#aaa] border-[#333] bg-[#151515]' },
}

const CHANNEL_LABEL: Record<string, string> = {
  api_tcp: 'API TCP',
  api_tls: 'TLS с доменом',
  api_http: 'HTTP-ответ',
  tls_no_sni: 'TLS без SNI',
  wdtt_udp: 'wdtt UDP',
  wg_udp: 'WireGuard UDP',
  agent_tcp: 'cell-agent TCP',
  socks_tcp: 'SOCKS TCP',
  ping: 'ICMP ping',
  dns: 'DNS',
}

function channelLabel(c: string): string {
  return CHANNEL_LABEL[c] || c
}

function fmtInterval(sec: number): string {
  if (sec % 3600 === 0) return `${sec / 3600} ч`
  if (sec % 60 === 0) return `${sec / 60} мин`
  return `${sec} с`
}

function VerdictCard({ verdict }: { verdict: Verdict }) {
  return (
    <div className="bg-[#0a0a0a] border border-[#242424] rounded-lg px-3 py-2">
      <p className="text-sm text-[#eee]">
        <span className="text-[#ddd] mr-2">{verdict.target}</span>
        {verdict.summary || verdict.title}
      </p>
    </div>
  )
}

function ruFraction(ru: Vantage): string {
  const asked = ru.asked ?? ru.nodes?.length ?? ru.total
  return `${ru.ok} из ${asked || ru.total}`
}

function TargetRow({
  target,
  probeCount,
  liveOnline,
}: {
  target: Target
  probeCount: number
  liveOnline?: number
}) {
  const chips = Object.entries(target.ru).map(([ch, ru]) => {
    const asked = ru.asked ?? ru.nodes?.length ?? probeCount
    const unanswered = asked > ru.ok + ru.failed
    const bad = ru.failed > 0
    const rtt = ru.median_latency_ms != null ? ` ${Math.round(ru.median_latency_ms)} мс` : ''
    return {
      ch,
      text: `${channelLabel(ch)} ${ruFraction({ ...ru, asked })}` + rtt,
      bad,
      unanswered,
    }
  })
  const closedAgent = target.ai_exit && !target.ru.agent_tcp
  return (
    <div className="bg-[#0a0a0a] border border-[#222] rounded-lg px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs">
        <span className="text-[#ddd] font-medium">{target.name}</span>
        <span className="text-[#666] font-mono">{target.host}</span>
        <span className="text-[#555]">онлайн {liveOnline ?? target.online_count}</span>
        {target.ai_exit && <span className="text-sky-400/90">ИИ</span>}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
        {chips.map(c => (
          <span key={c.ch} className={c.bad ? 'text-amber-300' : c.unanswered ? 'text-[#888]' : 'text-emerald-400'}>{c.text}</span>
        ))}
        {closedAgent && <span className="text-[#888]">с интернета закрыт</span>}
        {chips.length === 0 && !closedAgent && (
          <span className="text-[#666]">пробы с РФ ещё не сняты</span>
        )}
        {target.clients && target.clients.failures > 0 && (
          <span className="text-[#888]">отказы {target.clients.failures}</span>
        )}
      </div>
    </div>
  )
}

export default function HiveAvailabilityPanel({
  token,
  onlineByHost,
}: {
  token: string
  onlineByHost?: Record<string, number>
}) {
  const authHeaders = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token])
  const jsonHeaders = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token],
  )

  const [report, setReport] = useState<Report | null>(null)
  const [settings, setSettings] = useState<AgentSettings | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const res = await fetch('/api/admin/hive/availability', { headers: authHeaders })
    if (!res.ok) {
      setError('Не удалось получить отчёт о доступности')
      return null
    }
    const data = await res.json().catch(() => ({}))
    setReport(data.report || null)
    setSettings(data.settings || null)
    setError(null)
    return data as { report?: Report | null; settings?: AgentSettings | null; running?: boolean }
  }, [authHeaders])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    // Агент считает раз в 30 мин — чаще опрашивать нет смысла, это лишние запросы.
    const t = setInterval(() => { void load() }, 180000)
    return () => clearInterval(t)
  }, [load])

  const runNow = async () => {
    setRunning(true)
    setError(null)
    const prevRun = settings?.last_run || null
    try {
      const res = await fetch('/api/admin/hive/availability/run', { method: 'POST', headers: authHeaders })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(typeof data.detail === 'string' ? data.detail : 'Не удалось запустить проверку')
        return
      }
      // Проверка на сервере ~1–2 мин — не ждём HTTP, опрашиваем готовый отчёт.
      for (let i = 0; i < 90; i++) {
        await new Promise(r => setTimeout(r, 2000))
        const snap = await load()
        if (!snap) continue
        const last = snap.settings?.last_run || null
        const done = !snap.running && last && last !== prevRun
        if (done) return
        // Если флаг running сбросился на другом воркере — берём свежий отчёт по ts.
        if (!snap.running && snap.report?.ts) {
          const ageMs = Date.now() - new Date(snap.report.ts).getTime()
          if (ageMs >= 0 && ageMs < 180_000) return
        }
      }
      setError('Проверка ещё идёт или ответ задерживается — обновите страницу через минуту')
    } catch {
      setError('Связь оборвалась. Если проверка уже шла — отчёт появится сам, обновите через минуту')
      await load()
    } finally {
      setRunning(false)
    }
  }

  const patchSettings = async (patch: Partial<AgentSettings>) => {
    const res = await fetch('/api/admin/hive/availability/settings', {
      method: 'PUT',
      headers: jsonHeaders,
      body: JSON.stringify(patch),
    })
    if (!res.ok) {
      setError('Не удалось сохранить настройки агента')
      return
    }
    const data = await res.json().catch(() => ({}))
    if (data.settings) setSettings(data.settings)
  }

  const status = report?.status || 'unknown'
  const meta = STATUS_META[status] || STATUS_META.unknown
  const problems = (report?.verdicts || []).filter(v => v.kind !== 'ok')
  const ruNodes = report?.vantage?.ru_nodes || []

  return (
    <div className="bg-[#111] border border-[#222] rounded-xl p-4 md:p-5">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <h2 className="font-medium flex items-center gap-2">
            <Radar className="w-4 h-4 text-[#888]" />
            Доступность
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2.5 py-1 rounded-lg border ${meta.cls}`}>
            {status === 'ok' ? (
              <ShieldCheck className="w-3.5 h-3.5 inline mr-1 -mt-0.5" />
            ) : (
              <ShieldAlert className="w-3.5 h-3.5 inline mr-1 -mt-0.5" />
            )}
            {meta.label}
          </span>
          <button
            type="button"
            onClick={runNow}
            disabled={running}
            className="text-xs px-3 py-1.5 rounded-lg border border-[#333] bg-[#1a1a1a] text-[#ddd] cursor-pointer transition duration-100 hover:text-white hover:border-[#555] hover:bg-[#222] active:scale-[0.96] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {running ? (
              <><Loader2 className="w-3.5 h-3.5 inline mr-1 animate-spin" /> Проверяю…</>
            ) : (
              <><Play className="w-3.5 h-3.5 inline mr-1 -mt-0.5" /> Проверить сейчас</>
            )}
          </button>
        </div>
      </div>

      {settings && (
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-[#888]">
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={settings.enabled}
              onChange={e => void patchSettings({ enabled: e.target.checked })}
              className="accent-blue-500"
            />
            Агент включён
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={settings.external_enabled}
              onChange={e => void patchSettings({ external_enabled: e.target.checked })}
              className="accent-blue-500"
            />
            Пробы с российских нод
          </label>
          <span>
            Интервал:{' '}
            <select
              value={settings.interval_sec}
              onChange={e => void patchSettings({ interval_sec: Number(e.target.value) })}
              className="bg-[#0a0a0a] border border-[#333] rounded px-1.5 py-0.5 text-[#ddd]"
            >
              {[300, 600, 900, 1800, 3600, 10800].map(s => (
                <option key={s} value={s}>{fmtInterval(s)}</option>
              ))}
            </select>
          </span>
          {ruNodes.length > 0 && (
            <span className="text-[#888]">ноды РФ: {ruNodes.length}</span>
          )}
          {settings.last_run && (
            <span className="text-[#555]">
              Последний прогон: {new Date(settings.last_run).toLocaleString('ru-RU')}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="mt-3 bg-red-950/40 border border-red-800 text-red-300 text-xs rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {report ? (
        <>
          {report.relay_plan?.hops && report.relay_plan.hops.length > 0 && (
            <p className="mt-3 text-xs text-[#888]">
              Кольцо: {report.relay_plan.hops.map(h => h.name).join(', ')}.
              Новый сервер попадает сюда сам. VPN идёт на выбранный сервер напрямую.
            </p>
          )}
          {problems.length > 0 && (
            <div className="mt-3 space-y-2">
              {problems.map((v, i) => <VerdictCard key={`${v.target}-${v.kind}-${i}`} verdict={v} />)}
            </div>
          )}
          <div className="mt-3 space-y-2">
            {report.targets.map(t => (
              <TargetRow
                key={`${t.name}-${t.host}`}
                target={t}
                probeCount={ruNodes.length || 3}
                liveOnline={onlineByHost?.[t.host]}
              />
            ))}
          </div>
        </>
      ) : (
        <p className="mt-3 text-xs text-[#666]">Отчёта ещё нет.</p>
      )}
    </div>
  )
}
