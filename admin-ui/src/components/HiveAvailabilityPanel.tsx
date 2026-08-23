import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Radar, ShieldAlert, ShieldCheck, Play, Loader2, ChevronDown, ChevronRight,
  Copy, Check, BookOpen, Activity,
} from 'lucide-react'

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
  status: string
  online_count: number
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

type KnowledgeItem = {
  kind: string
  title: string
  severity: string
  how_it_works: string
  signals: string[]
  fixes: string[]
  commands: string[]
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  ok: { label: 'Доступно из РФ', cls: 'text-emerald-400 border-emerald-800 bg-emerald-950/40' },
  degraded: { label: 'Деградация', cls: 'text-amber-300 border-amber-800 bg-amber-950/40' },
  blocked: { label: 'Есть блокировка', cls: 'text-red-400 border-red-800 bg-red-950/40' },
  down: { label: 'Сервис не отвечает', cls: 'text-red-400 border-red-800 bg-red-950/40' },
  unknown: { label: 'Данных мало', cls: 'text-[#aaa] border-[#333] bg-[#151515]' },
}

const SEVERITY_CLS: Record<string, string> = {
  critical: 'text-red-400',
  error: 'text-red-300',
  warning: 'text-amber-300',
  info: 'text-emerald-400',
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

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text)
        setDone(true)
        setTimeout(() => setDone(false), 1500)
      }}
      title="Скопировать"
      className="shrink-0 text-[#666] hover:text-white transition"
    >
      {done ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
    </button>
  )
}

function VerdictCard({ verdict }: { verdict: Verdict }) {
  const [open, setOpen] = useState(verdict.severity === 'critical' || verdict.severity === 'error')
  return (
    <div className="bg-[#0a0a0a] border border-[#242424] rounded-lg px-3 py-2.5">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-start gap-2 text-left"
      >
        {open ? (
          <ChevronDown className="w-4 h-4 mt-0.5 text-[#666] shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 mt-0.5 text-[#666] shrink-0" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`uppercase ${SEVERITY_CLS[verdict.severity] || 'text-[#aaa]'}`}>
              {verdict.severity}
            </span>
            <span className="text-[#ddd] font-medium">{verdict.target}</span>
            <span className="text-[#666] font-mono">{verdict.host}</span>
            {verdict.channel && (
              <span className="text-violet-300">{channelLabel(verdict.channel)}</span>
            )}
            <span className="text-[#555]">уверенность {Math.round(verdict.confidence * 100)}%</span>
          </div>
          <p className="text-sm text-[#eee] mt-1">{verdict.title}</p>
          <p className="text-xs text-[#999] mt-0.5">{verdict.summary}</p>
        </div>
      </button>

      {open && (
        <div className="mt-3 pl-6 space-y-3">
          {verdict.evidence.length > 0 && (
            <div>
              <p className="text-[10px] uppercase text-[#666] mb-1">Почему так решили</p>
              <ul className="space-y-0.5">
                {verdict.evidence.map((e, i) => (
                  <li key={i} className="text-xs text-[#aaa]">· {e}</li>
                ))}
              </ul>
            </div>
          )}
          {verdict.fixes.length > 0 && (
            <div>
              <p className="text-[10px] uppercase text-emerald-500/80 mb-1">Решение</p>
              <ol className="space-y-1">
                {verdict.fixes.map((f, i) => (
                  <li key={i} className="text-xs text-[#ddd] flex gap-2">
                    <span className="text-[#555] shrink-0">{i + 1}.</span>
                    <span>{f}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {verdict.commands.length > 0 && (
            <div>
              <p className="text-[10px] uppercase text-[#666] mb-1">Команды</p>
              <div className="space-y-1">
                {verdict.commands.map((c, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2 bg-[#050505] border border-[#1e1e1e] rounded px-2 py-1"
                  >
                    <code className="text-[11px] text-[#9ecbff] font-mono break-all flex-1">{c}</code>
                    <CopyButton text={c} />
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TargetRow({ target }: { target: Target }) {
  const channels = useMemo(() => {
    const set = new Set<string>([
      ...Object.keys(target.local),
      ...Object.keys(target.ru),
      ...Object.keys(target.peer),
    ])
    return Array.from(set)
  }, [target])

  return (
    <div className="bg-[#0a0a0a] border border-[#222] rounded-lg px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-[#ddd] font-medium">{target.name}</span>
        <span className="text-[#666] font-mono">{target.host}</span>
        {target.domain && <span className="text-[#555]">{target.domain}</span>}
        <span className="text-[#555]">статус {target.status || '—'}</span>
        <span className="text-[#555]">онлайн {target.online_count}</span>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-[#555] text-left">
              <th className="font-normal py-1 pr-3">Канал</th>
              <th className="font-normal py-1 pr-3">Локально</th>
              <th className="font-normal py-1 pr-3">Из РФ</th>
              <th className="font-normal py-1 pr-3">RTT</th>
              <th className="font-normal py-1">Ошибки</th>
            </tr>
          </thead>
          <tbody>
            {channels.map(ch => {
              const local = target.local[ch]
              const ru = target.ru[ch]
              const peer = target.peer[ch]
              return (
                <tr key={ch} className="border-t border-[#1a1a1a]">
                  <td className="py-1 pr-3 text-[#bbb]">{channelLabel(ch)}</td>
                  <td className="py-1 pr-3">
                    {local ? (
                      <span className={local.ok ? 'text-emerald-400' : 'text-red-400'}>
                        {local.ok ? (local.inconclusive ? 'слушает' : 'ok') : local.error_kind || 'fail'}
                      </span>
                    ) : peer ? (
                      <span className={peer.ok ? 'text-emerald-400' : 'text-red-400'}>
                        {peer.ok ? 'ok (с соты)' : peer.error_kind || 'fail'}
                      </span>
                    ) : (
                      <span className="text-[#444]">—</span>
                    )}
                  </td>
                  <td className="py-1 pr-3">
                    {ru ? (
                      <span className={ru.failed === 0 ? 'text-emerald-400' : ru.ok === 0 ? 'text-red-400' : 'text-amber-300'}>
                        {ru.ok}/{ru.total}
                      </span>
                    ) : (
                      <span className="text-[#444]">нет проб</span>
                    )}
                  </td>
                  <td className="py-1 pr-3 text-[#888]">
                    {ru?.median_latency_ms != null ? `${Math.round(ru.median_latency_ms)} мс` : '—'}
                  </td>
                  <td className="py-1 text-[#777]">
                    {ru && Object.keys(ru.error_kinds).length > 0
                      ? Object.entries(ru.error_kinds).map(([k, v]) => `${k}×${v}`).join(', ')
                      : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {target.clients && (
        <p className="text-[11px] text-[#888] mt-2">
          Клиенты: {target.clients.failures} отказов за {target.clients.window_minutes} мин ·
          стадии {Object.entries(target.clients.by_stage).map(([k, v]) => `${k}×${v}`).join(', ') || '—'} ·
          сети {Object.entries(target.clients.by_network).map(([k, v]) => `${k}×${v}`).join(', ') || '—'}
        </p>
      )}
    </div>
  )
}

export default function HiveAvailabilityPanel({ token }: { token: string }) {
  const authHeaders = useMemo(() => ({ Authorization: `Bearer ${token}` }), [token])
  const jsonHeaders = useMemo(
    () => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }),
    [token],
  )

  const [report, setReport] = useState<Report | null>(null)
  const [settings, setSettings] = useState<AgentSettings | null>(null)
  const [knowledge, setKnowledge] = useState<KnowledgeItem[]>([])
  const [showKnowledge, setShowKnowledge] = useState(false)
  const [showTargets, setShowTargets] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    const res = await fetch('/api/admin/hive/availability', { headers: authHeaders })
    if (!res.ok) {
      setError('Не удалось получить отчёт о доступности')
      return
    }
    const data = await res.json().catch(() => ({}))
    setReport(data.report || null)
    setSettings(data.settings || null)
    setError(null)
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
    try {
      const res = await fetch('/api/admin/hive/availability/run', { method: 'POST', headers: authHeaders })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        setError(typeof data.detail === 'string' ? data.detail : 'Проверка не выполнена')
        return
      }
      setReport(data.report || null)
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

  const loadKnowledge = async () => {
    setShowKnowledge(s => !s)
    if (knowledge.length > 0) return
    const res = await fetch('/api/admin/hive/availability/knowledge', { headers: authHeaders })
    if (!res.ok) return
    const data = await res.json().catch(() => ({}))
    setKnowledge(Array.isArray(data.items) ? data.items : [])
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
            Доступность и блокировки (DPI / ТСПУ)
          </h2>
          <p className="text-xs text-[#666] mt-0.5 max-w-2xl">
            Агент проверяет, видят ли клиенты из РФ наши серверы, определяет способ блокировки
            и даёт готовое решение. Пробы только читают: сервисы не перезапускаются.
          </p>
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
          <span>
            Нод РФ:{' '}
            <select
              value={settings.ru_nodes}
              onChange={e => void patchSettings({ ru_nodes: Number(e.target.value) })}
              className="bg-[#0a0a0a] border border-[#333] rounded px-1.5 py-0.5 text-[#ddd]"
            >
              {[2, 3, 4, 5, 6, 8].map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </span>
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
          <div className="mt-3 bg-[#0d0d0d] border border-[#242424] rounded-lg px-3 py-2.5">
            <p className="text-sm text-[#ddd]">{report.summary}</p>
            <p className="text-[11px] text-[#666] mt-1">
              {new Date(report.ts).toLocaleString('ru-RU')} · проверка {report.duration_sec} с ·
              российские ноды: {ruNodes.length > 0 ? ruNodes.join(', ') : 'нет'} ·
              внешних проверок {report.vantage?.checks ?? 0}
            </p>
            {report.warnings.map((w, i) => (
              <p key={i} className="text-[11px] text-amber-300/90 mt-1">{w}</p>
            ))}
          </div>

          {problems.length > 0 ? (
            <div className="mt-3 space-y-2">
              <p className="text-xs text-[#888]">Найдено проблем: {problems.length}</p>
              {problems.map((v, i) => <VerdictCard key={`${v.target}-${v.kind}-${i}`} verdict={v} />)}
            </div>
          ) : (
            <p className="mt-3 text-xs text-emerald-400/90">
              Блокировок не обнаружено — все проверенные каналы видны из РФ.
            </p>
          )}

          <button
            type="button"
            onClick={() => setShowTargets(s => !s)}
            className="mt-3 text-xs text-[#888] hover:text-white flex items-center gap-1.5"
          >
            <Activity className="w-3.5 h-3.5" />
            {showTargets ? 'Скрыть' : 'Показать'} детали по узлам и каналам
          </button>
          {showTargets && (
            <div className="mt-2 space-y-2">
              {report.targets.map(t => <TargetRow key={`${t.name}-${t.host}`} target={t} />)}
            </div>
          )}
        </>
      ) : (
        <p className="mt-3 text-xs text-[#666]">
          Отчётов пока нет. Нажмите «Проверить сейчас» или дождитесь автоматического прогона.
        </p>
      )}

      <button
        type="button"
        onClick={loadKnowledge}
        className="mt-4 text-xs text-[#888] hover:text-white flex items-center gap-1.5"
      >
        <BookOpen className="w-3.5 h-3.5" />
        {showKnowledge ? 'Скрыть' : 'Открыть'} справочник: как блокируют в РФ и что делать
      </button>
      {showKnowledge && (
        <div className="mt-2 space-y-2 max-h-96 overflow-auto pr-1">
          {knowledge.map(item => (
            <div key={item.kind} className="bg-[#0a0a0a] border border-[#222] rounded-lg px-3 py-2">
              <p className={`text-xs uppercase ${SEVERITY_CLS[item.severity] || 'text-[#aaa]'}`}>
                {item.severity}
              </p>
              <p className="text-sm text-[#ddd] mt-0.5">{item.title}</p>
              <p className="text-xs text-[#888] mt-1">{item.how_it_works}</p>
              <p className="text-[10px] uppercase text-[#666] mt-2 mb-0.5">Признаки</p>
              <ul>{item.signals.map((s, i) => <li key={i} className="text-xs text-[#999]">· {s}</li>)}</ul>
              <p className="text-[10px] uppercase text-emerald-500/80 mt-2 mb-0.5">Решение</p>
              <ul>{item.fixes.map((f, i) => <li key={i} className="text-xs text-[#ccc]">— {f}</li>)}</ul>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
