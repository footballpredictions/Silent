import { useEffect, useState } from 'react'
import { Cpu, HardDrive, MemoryStick, Users, Wifi, Hash, RefreshCw } from 'lucide-react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

interface Stats {
  system: {
    cpu_percent: number
    memory_total_gb: number
    memory_used_gb: number
    memory_percent: number
    disk_total_gb: number
    disk_used_gb: number
    disk_percent: number
  }
  users: {
    total: number
    active_subscriptions: number
    connected_devices: number
  }
  vk_hashes: Array<{
    slot: number
    hash: string
    is_active: boolean
    fail_count: number
    last_checked: string | null
  }>
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

export default function DashboardPage({ token, onUnauthorized }: { token: string; onUnauthorized?: () => void }) {
  const [stats, setStats] = useState<Stats | null>(null)
  const [cpuHistory, setCpuHistory] = useState<{ t: string; v: number }[]>([])
  const [loading, setLoading] = useState(false)

  const fetchStats = async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/admin/stats', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.status === 401) {
        onUnauthorized?.()
        return
      }
      if (!res.ok) return
      const data: Stats = await res.json()
      if (!data?.system) return
      setStats(data)
      setCpuHistory(prev => [
        ...prev.slice(-19),
        { t: new Date().toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit', second: '2-digit' }), v: data.system.cpu_percent },
      ])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStats()
    const interval = setInterval(fetchStats, 5000)
    return () => clearInterval(interval)
  }, [])

  if (!stats) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <div className="animate-spin w-8 h-8 border-2 border-white border-t-transparent rounded-full" />
        <p className="text-[#666] text-sm">Загрузка статистики...</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Дашборд</h1>
        <button
          onClick={fetchStats}
          disabled={loading}
          className="flex items-center gap-2 text-xs text-[#666] hover:text-white transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Обновить
        </button>
      </div>

      {/* User stats */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard icon={Users} label="Пользователей" value={stats.users.total} />
        <StatCard icon={Wifi} label="Активных подписок" value={stats.users.active_subscriptions} />
        <StatCard icon={Wifi} label="Подключений" value={stats.users.connected_devices} />
      </div>

      {/* System */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-[#111] border border-[#222] rounded-xl p-5">
          <h3 className="text-xs text-[#666] uppercase tracking-wider mb-4 flex items-center gap-2">
            <Cpu className="w-3.5 h-3.5" /> Системные ресурсы
          </h3>
          <ProgressBar percent={stats.system.cpu_percent} label={`CPU — ${stats.system.cpu_percent.toFixed(1)}%`} />
          <ProgressBar percent={stats.system.memory_percent} label={`RAM — ${stats.system.memory_used_gb} / ${stats.system.memory_total_gb} GB`} />
          <ProgressBar percent={stats.system.disk_percent} label={`Диск — ${stats.system.disk_used_gb} / ${stats.system.disk_total_gb} GB`} />
        </div>

        <div className="bg-[#111] border border-[#222] rounded-xl p-5">
          <h3 className="text-xs text-[#666] uppercase tracking-wider mb-4">CPU — история</h3>
          <ResponsiveContainer width="100%" height={120}>
            <AreaChart data={cpuHistory}>
              <XAxis dataKey="t" hide />
              <YAxis domain={[0, 100]} hide />
              <Tooltip
                contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: 8, fontSize: 12 }}
                formatter={(v: number) => [`${v.toFixed(1)}%`, 'CPU']}
              />
              <Area type="monotone" dataKey="v" stroke="#fff" fill="#ffffff15" strokeWidth={1.5} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* VK Hashes */}
      <div className="bg-[#111] border border-[#222] rounded-xl p-5">
        <h3 className="text-xs text-[#666] uppercase tracking-wider mb-4 flex items-center gap-2">
          <Hash className="w-3.5 h-3.5" /> VK Туннельные хеши
        </h3>
        <div className="space-y-2">
          {stats.vk_hashes.length === 0 && (
            <p className="text-[#555] text-sm">Хеши не созданы. Перейдите в раздел "VK / Тоннели".</p>
          )}
          {stats.vk_hashes.map(h => (
            <div key={h.slot} className="flex items-center gap-4 py-2 border-b border-[#1a1a1a] last:border-0">
              <div className={`w-2 h-2 rounded-full ${h.is_active ? 'bg-green-400' : 'bg-red-400'}`} />
              <span className="text-xs text-[#666]">Слот {h.slot}</span>
              <span className="font-mono text-sm flex-1">{h.hash}</span>
              <span className="text-xs text-[#555]">Сбоев: {h.fail_count}</span>
              <span className={`text-xs ${h.is_active ? 'text-green-400' : 'text-red-400'}`}>
                {h.is_active ? 'Активен' : 'Неактивен'}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
