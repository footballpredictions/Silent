import { useCallback, useEffect, useState } from 'react'
import { Hexagon, Plus, RefreshCw, Trash2, Wifi, WifiOff, Crown, Loader2, Cpu, HardDrive } from 'lucide-react'

interface CellLoad {
  cpu_percent: number
  memory_percent: number
  build_running?: boolean
  vpn_overloaded?: boolean
  wdtt_active?: boolean
}

interface HiveCell {
  id: string
  name: string
  is_queen: boolean
  public_ip: string
  wdtt_port: number
  wg_port: number
  online_count: number
  assigned_devices: number
  status: string
  last_error: string | null
  load?: CellLoad
}

interface HiveSummary {
  cells_total: number
  cells_active: number
  total_online_vpn: number
  worker_cells: number
  queen_accepting_vpn: boolean
  queen_load: CellLoad
  cpu_threshold: number
  mem_threshold: number
}

const statusLabel: Record<string, string> = {
  active: 'Активна',
  provisioning: 'Настройка…',
  pending: 'Подключение…',
  draining: 'Вывод из эксплуатации',
  offline: 'Выключена',
  error: 'Ошибка',
}

function fmtLoad(cell: HiveCell, cpuThreshold: number, memThreshold: number): string {
  if (!cell.load) return ''
  const { cpu_percent, memory_percent, build_running, wdtt_active } = cell.load
  const cpuHot = cpu_percent >= cpuThreshold
  const memHot = memory_percent >= memThreshold
  const parts = [
    `CPU ${cpu_percent}%${cpuHot ? ' ⚠' : ''}`,
    `RAM ${memory_percent}%${memHot ? ' ⚠' : ''}`,
  ]
  if (cell.is_queen && build_running) parts.push('сборка OTA')
  if (!cell.is_queen && wdtt_active === false) parts.push('wdtt не запущен')
  return parts.join(' · ')
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

  const load = useCallback(async (silent = false) => {
    if (!silent) setError(null)
    const [cellsRes, sumRes] = await Promise.all([
      fetch('/api/admin/hive/cells', { headers: { Authorization: `Bearer ${token}` } }),
      fetch('/api/admin/hive/summary', { headers: { Authorization: `Bearer ${token}` } }),
    ])
    if (!cellsRes.ok) {
      setError('Не удалось загрузить соты')
      setLoading(false)
      return
    }
    setCells(await cellsRes.json())
    if (sumRes.ok) setSummary(await sumRes.json())
    setMetricsAt(new Date())
    setLoading(false)
  }, [token])

  useEffect(() => { load() }, [load])

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

  const needsAgentUpgrade = (cell: HiveCell) =>
    !cell.is_queen && cell.status === 'active' && cell.load &&
    cell.load.cpu_percent === 0 && cell.load.memory_percent === 0

  const upgradeAgent = async (cell: HiveCell) => {
    const password = prompt(`SSH root-пароль для «${cell.name}» (${cell.public_ip}):`)
    if (!password) return
    setBusy(cell.id)
    setError(null)
    try {
      const res = await fetch(`/api/admin/hive/cells/${cell.id}/upgrade-agent`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ password }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) setError(fmtDetail(data.detail))
      else {
        setSuccess(data.message || 'cell-agent обновлён')
        await load(true)
      }
    } finally {
      setBusy(null)
    }
  }

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

  const ql = summary?.queen_load

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Hexagon className="w-7 h-7" />
            Улей
          </h1>
          <p className="text-[#888] text-sm mt-1">
            Балансировка по CPU/RAM и онлайн VPN. Сборка OTA в полночь не считается перегрузкой.
          </p>
        </div>
        <button type="button" onClick={() => { setLoading(true); load() }}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#1a1a1a] text-sm text-[#aaa] hover:text-white">
          <RefreshCw className="w-4 h-4" /> Обновить
        </button>
      </div>
      {metricsAt && (
        <p className="text-xs text-[#555] -mt-3">
          Метрики CPU/RAM обновляются каждые 10 с · последнее: {metricsAt.toLocaleTimeString('ru')}
        </p>
      )}

      {summary && ql && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-[#111] border border-[#222] rounded-xl p-4">
            <p className="text-[#666] text-xs uppercase">Онлайн VPN</p>
            <p className="text-2xl font-semibold mt-1">{summary.total_online_vpn}</p>
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
            <p className="text-[#666] text-xs uppercase">Режим</p>
            <p className="text-sm font-medium mt-2">
              {ql.build_running ? (
                <span className="text-blue-400">Сборка OTA — VPN на Улье</span>
              ) : summary.queen_accepting_vpn ? (
                <span className="text-emerald-400">Улей принимает VPN</span>
              ) : (
                <span className="text-orange-400">Перегруз — новые на соты</span>
              )}
            </p>
          </div>
        </div>
      )}

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
                    {cell.is_queen && <span className="text-xs bg-amber-950 text-amber-300 px-2 py-0.5 rounded">Улей</span>}
                    <span className="text-xs text-[#888]">{statusLabel[cell.status] || cell.status}</span>
                  </div>
                  <p className="text-sm text-[#888] mt-1 font-mono">{cell.public_ip}:{cell.wdtt_port}</p>
                  {cell.load && summary && (
                    <p className={`text-xs mt-1 ${cell.load.vpn_overloaded || (cell.load.cpu_percent >= summary.cpu_threshold) || (cell.load.memory_percent >= summary.mem_threshold) ? 'text-amber-400' : 'text-[#666]'}`}>
                      {fmtLoad(cell, summary.cpu_threshold, summary.mem_threshold)}
                    </p>
                  )}
                  {!cell.load && !cell.is_queen && cell.status === 'active' && (
                    <p className="text-xs text-[#555] mt-1">CPU/RAM: cell-agent недоступен</p>
                  )}
                  {needsAgentUpgrade(cell) && (
                    <button type="button" disabled={busy === cell.id} onClick={() => upgradeAgent(cell)}
                      className="text-xs mt-1 text-blue-400 hover:text-blue-300 underline disabled:opacity-50">
                      Обновить мониторинг на соте (SSH)
                    </button>
                  )}
                  {cell.assigned_devices > 0 && !cell.is_queen && (
                    <p className="text-xs text-[#666] mt-0.5">назначено устройств: {cell.assigned_devices}</p>
                  )}
                  {cell.last_error && <p className="text-xs text-red-400 mt-2 whitespace-pre-wrap">{cell.last_error}</p>}
                </div>
                <div className="text-right">
                  <p className="text-lg font-semibold">{cell.online_count}</p>
                  <p className="text-xs text-[#666]">онлайн VPN</p>
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
