import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, Clock3, Loader2, Pause, Play, RefreshCw } from 'lucide-react'

type Role = 'issuer' | 'checker'
type Agent = {
  enabled: boolean
  state: 'running' | 'waiting' | 'cooldown' | 'disabled' | 'stopping' | 'error' | 'stale' | 'unknown'
  observed_at?: string
  started_at?: string
  last_completed_at?: string
  next_run_at?: string
  pause_until?: string | null
  last_message?: string
  last_batch?: { attempted: number; budget: number; alive: number; pending: number; dead: number; skipped: number }
  last_created?: number | null
  last_successful_at?: string
  progress?: { attempted: number; budget: number; successful: number }
  totals?: { since: string; attempted: number; successful: number; limited: number; confirmed_dead: number; skipped: number }
}
type Snapshot = {
  server_time: string
  agents: Record<Role, Agent>
  counts: { active: number; pending: number; dead: number }
  calls_ready: boolean
}

const names: Record<Agent['state'], string> = {
  running: 'Работает', waiting: 'Работает', cooldown: 'Пауза: ограничение VK',
  disabled: 'Отключён', stopping: 'Завершает работу', error: 'Ошибка выполнения',
  stale: 'Нет свежего сигнала', unknown: 'Ожидаем сигнал агента',
}
const button = 'inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-[#3a3a3a] px-3 py-2 text-sm font-medium text-[#eee] transition-colors hover:border-[#777] hover:bg-[#202020] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-400 disabled:cursor-not-allowed disabled:opacity-45'

function parsed(raw?: string | null) {
  if (!raw) return NaN
  return Date.parse(raw.replace(' UTC', 'Z').replace(' ', 'T'))
}

function msk(raw?: string | null) {
  const value = parsed(raw)
  if (!Number.isFinite(value)) return 'Нет данных'
  return new Date(value).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) + ' МСК'
}

function remaining(raw: string, now: number) {
  const seconds = Math.max(0, Math.ceil((parsed(raw) - now) / 1000))
  if (!Number.isFinite(seconds)) return '—'
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export default function VkAgentsPanel({ token }: { token: string }) {
  const [data, setData] = useState<Snapshot | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<Partial<Record<Role, boolean>>>({})
  const [messages, setMessages] = useState<Partial<Record<Role, string>>>({})
  const [receivedAt, setReceivedAt] = useState<number | null>(null)
  const [clock, setClock] = useState(Date.now())
  const loading = useRef(false)
  const abort = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    if (loading.current) return
    loading.current = true
    const controller = new AbortController()
    abort.current = controller
    try {
      const response = await fetch('/api/admin/vk/agents/status', {
        headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
      })
      if (!response.ok) throw new Error(response.status === 401 ? 'Сессия истекла. Войдите в админку снова.' : 'Не удалось обновить статус. Повторяем автоматически.')
      const next: Snapshot = await response.json()
      if (!next.agents?.issuer || !next.agents?.checker) throw new Error('Сервер пока не передал статусы двух агентов.')
      setData(next)
      setReceivedAt(Date.now())
      setError('')
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Нет связи с сервером.')
    } finally {
      loading.current = false
    }
  }, [token])

  useEffect(() => {
    void load()
    const poll = window.setInterval(() => { if (!document.hidden) void load() }, 5000)
    const tick = window.setInterval(() => setClock(Date.now()), 1000)
    const visible = () => { if (!document.hidden) void load() }
    document.addEventListener('visibilitychange', visible)
    return () => {
      abort.current?.abort()
      window.clearInterval(poll)
      window.clearInterval(tick)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [load])

  const command = async (role: Role, action: 'toggle' | 'run') => {
    if (!data) return
    setBusy(value => ({ ...value, [role]: true }))
    setMessages(value => ({ ...value, [role]: '' }))
    try {
      const response = await fetch(`/api/admin/vk/agents/${role}${action === 'run' ? '/run' : ''}`, {
        method: action === 'run' ? 'POST' : 'PATCH',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        ...(action === 'toggle' ? { body: JSON.stringify({ enabled: !data.agents[role].enabled }) } : {}),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Не удалось выполнить команду.')
      if (result.agents) { setData(result); setReceivedAt(Date.now()) }
      setMessages(value => ({ ...value, [role]: action === 'run' ? 'Запрос на запуск принят.' : data.agents[role].enabled ? 'Остановка запрошена. Текущий цикл завершится.' : 'Агент включён. Ожидаем начало цикла.' }))
      await load()
    } catch (e) {
      setMessages(value => ({ ...value, [role]: e instanceof Error ? e.message : 'Ошибка команды.' }))
    } finally {
      setBusy(value => ({ ...value, [role]: false }))
    }
  }

  const serverNow = receivedAt && data ? parsed(data.server_time) + clock - receivedAt : clock
  return (
    <section aria-labelledby="vk-agents-title" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="vk-agents-title" className="text-base font-semibold text-[#f5f5f5]">Работа агентов</h2>
          <p className="mt-1 text-sm text-[#aaa]">Проверка хешей и их замена управляются отдельно.</p>
        </div>
        <button type="button" className={button} onClick={() => void load()} aria-label="Обновить статусы агентов">
          <RefreshCw className="h-4 w-4" aria-hidden="true" /> Обновить
        </button>
      </div>
      {error && <p role="alert" className="rounded-lg border border-amber-800/60 bg-amber-950/20 p-3 text-sm text-amber-200">{error}{data ? ' Показаны последние полученные данные.' : ''}</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        {(['issuer', 'checker'] as Role[]).map(role => {
          const agent = data?.agents[role]
          const working = !error && (agent?.state === 'running' || agent?.state === 'stopping')
          const warning = !!error || (agent && ['cooldown', 'stale', 'error'].includes(agent.state))
          const healthy = !error && agent && ['running', 'waiting'].includes(agent.state)
          const stateColor = warning ? 'text-amber-200' : healthy ? 'text-emerald-300' : 'text-[#ccc]'
          return (
            <article key={role} aria-labelledby={`vk-${role}-title`} className="flex min-w-0 flex-col rounded-xl border border-[#2a2a2a] bg-[#111] p-5">
              <h3 id={`vk-${role}-title`} className="text-base font-semibold text-white">{role === 'issuer' ? 'Основной агент' : 'Проверяющий агент'}</h3>
              <p className="mt-2 min-h-10 text-sm leading-relaxed text-[#aaa]">{role === 'issuer' ? 'Создаёт недостающие хеши и заменяет подтверждённые мёртвые.' : 'Проверяет хеши VK и передаёт подтверждённые сбои основному агенту.'}</p>
              <p className={`mt-5 flex items-center gap-2 text-base font-semibold ${stateColor}`}>
                {working ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : agent?.state === 'cooldown' ? <Clock3 className="h-4 w-4" aria-hidden="true" /> : <Activity className="h-4 w-4" aria-hidden="true" />}
                {error ? 'Нет свежих данных с сервера' : agent ? names[agent.state] ?? 'Неизвестное состояние' : 'Получаем статус…'}
              </p>
              {agent && !error && ['waiting', 'running'].includes(agent.state) && <p className="mt-2 text-sm leading-relaxed text-[#ddd]">
                {role === 'issuer'
                  ? agent.state === 'running' ? 'Проверяет слоты и создаёт нужные хеши.' : data?.counts.dead ? 'Ожидает следующей попытки замены хешей из очереди.' : 'Очередь замены пуста. Агент дежурит и проверяет её каждые 30 секунд.'
                  : agent.state === 'running' ? `Проверяет текущую пачку${agent.progress ? `: ${agent.progress.attempted} из ${agent.progress.budget}, успешно ${agent.progress.successful}` : ''}.` : 'Обход хешей включён. Следующая пачка запустится автоматически.'}
              </p>}
              {agent?.pause_until && <div className="mt-3 border-t border-[#2a2a2a] pt-3 text-sm text-amber-200">
                <p>VK ограничил запросы. Агент возобновит попытки автоматически, выполненные проверки сохраняются.</p>
                <p className="mt-1 tabular-nums">До {msk(agent.pause_until)} · осталось {remaining(agent.pause_until, serverNow)}</p>
              </div>}
              {agent?.state === 'stale' && <p className="mt-2 text-sm text-amber-200">Агент давно не подтверждал работу. Проверьте журнал сервера.</p>}
              <dl className="mt-4 space-y-3 border-t border-[#2a2a2a] pt-4 text-sm">
                {role === 'issuer' && <>
                  <div className="flex justify-between gap-3"><dt className="text-[#aaa]">Активных хешей</dt><dd className="tabular-nums text-[#eee]">{data?.counts.active.toLocaleString('ru-RU') ?? '—'}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-[#aaa]">Создано в последнем цикле</dt><dd className="tabular-nums text-[#eee]">{agent?.last_created ?? 'Нет данных'}</dd></div>
                </>}
                {role === 'checker' && <>
                  <div className="flex justify-between gap-3"><dt className="text-[#aaa]">Хешей для обхода</dt><dd className="tabular-nums text-[#eee]">{data?.counts.active.toLocaleString('ru-RU') ?? '—'}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-[#aaa]">Завершено проверок</dt><dd className="tabular-nums text-[#eee]">{agent?.totals?.successful.toLocaleString('ru-RU') ?? '—'}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-[#aaa]">Мёртвых подтверждено</dt><dd className="tabular-nums text-[#eee]">{agent?.totals?.confirmed_dead ?? '—'}</dd></div>
                  <div className="flex justify-between gap-3"><dt className="text-[#aaa]">Отказов из-за лимита VK</dt><dd className="tabular-nums text-[#eee]">{agent?.totals?.limited ?? '—'}</dd></div>
                </>}
                <div className="flex justify-between gap-3"><dt className="text-[#aaa]">{role === 'issuer' ? 'Ожидают замены' : 'Ожидают подтверждения'}</dt><dd className="tabular-nums text-[#eee]">{data ? (role === 'issuer' ? data.counts.dead : data.counts.pending).toLocaleString('ru-RU') : '—'}</dd></div>
              </dl>
              {role === 'checker' && <p className="mt-4 text-sm leading-relaxed text-[#bbb]">{agent?.totals ? `Счётчики с ${msk(agent.totals.since)}. Это число проверок; один хеш может проверяться повторно.` : 'Накопленный счётчик появится после следующей попытки проверки.'}</p>}
              <details className="mt-4 text-sm text-[#bbb]">
                <summary className="cursor-pointer py-1 text-[#ddd] focus-visible:outline focus-visible:outline-blue-400">Подробности работы</summary>
                <dl className="mt-3 space-y-2">
                  <div className="flex flex-wrap justify-between gap-x-3 gap-y-1"><dt>Последний сигнал</dt><dd className="tabular-nums">{msk(agent?.observed_at)}</dd></div>
                  <div className="flex flex-wrap justify-between gap-x-3 gap-y-1"><dt>Последний результат</dt><dd className="tabular-nums">{msk(agent?.last_completed_at)}</dd></div>
                  {agent?.enabled && agent.next_run_at && <div className="flex flex-wrap justify-between gap-x-3 gap-y-1"><dt>Следующий цикл</dt><dd className="tabular-nums">{msk(agent.next_run_at)}</dd></div>}
                </dl>
                {role === 'checker' && agent?.last_batch && <p className="mt-3 leading-relaxed">Только последняя попытка: успешно {agent.last_batch.alive + agent.last_batch.pending + agent.last_batch.dead}, пропущено {agent.last_batch.skipped}{agent.last_batch.attempted > agent.last_batch.alive + agent.last_batch.pending + agent.last_batch.dead + agent.last_batch.skipped ? '; остановлена ограничением VK' : ''}. Это не итог за всё время.</p>}
              </details>
              <div className="mt-auto flex flex-wrap gap-2 pt-5">
                <button type="button" className={button} disabled={!agent || busy[role] || !!error || agent.state === 'stopping'} onClick={() => void command(role, 'toggle')} aria-label={`${agent?.enabled ? 'Остановить' : 'Включить'} ${role === 'issuer' ? 'основного' : 'проверяющего'} агента`}>
                  {busy[role] ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : agent?.enabled ? <Pause className="h-4 w-4" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
                  {agent?.enabled ? 'Остановить' : 'Включить'}
                </button>
                <button type="button" className={button} disabled={!agent?.enabled || busy[role] || !!error || working || agent?.state === 'cooldown' || (role === 'issuer' && !data?.calls_ready)} onClick={() => void command(role, 'run')} aria-label={`${role === 'issuer' ? 'Создать и заменить хеши' : 'Проверить хеши'} сейчас`}>
                  <Play className="h-4 w-4" aria-hidden="true" /> {role === 'issuer' ? 'Выполнить сейчас' : 'Проверить сейчас'}
                </button>
              </div>
              {role === 'issuer' && data && !data.calls_ready && <p className="mt-3 text-sm text-amber-200">Для создания хешей подключите VK-аккаунт ниже.</p>}
              {messages[role] && <p role="status" className="mt-3 text-sm text-[#ccc]">{messages[role]}</p>}
            </article>
          )
        })}
      </div>
      <p className="text-sm text-[#999]">Статусы обновляются каждые 5 секунд. Остановка агентов не отключает работающие VPN-сеансы.</p>
    </section>
  )
}
