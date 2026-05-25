import { useState, useEffect, useRef } from 'react'

interface LogEntry {
  t: string
  lvl: string
  name: string
  msg: string
}

const LVL_COLOR: Record<string, string> = {
  DEBUG:    'text-gray-400',
  INFO:     'text-blue-400',
  WARNING:  'text-yellow-400',
  ERROR:    'text-red-400',
  CRITICAL: 'text-red-600 font-bold',
}

export default function LogsPage({ token }: { token: string }) {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [filter, setFilter] = useState<string>('ALL')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const fetchLogs = async () => {
    try {
      setLoading(true)
      const res = await fetch('/api/admin/logs', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) return
      const data = await res.json()
      setLogs(data.logs || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchLogs()
    const interval = setInterval(fetchLogs, 3000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  const levels = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

  const visible = logs.filter(l => {
    const lvlOk = filter === 'ALL' || l.lvl === filter
    const searchOk = !search || l.msg.toLowerCase().includes(search.toLowerCase()) || l.name.toLowerCase().includes(search.toLowerCase())
    return lvlOk && searchOk
  })

  return (
    <div className="flex flex-col h-full gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Логи API</h1>
        <div className="flex items-center gap-2">
          <span className={`text-xs ${loading ? 'text-yellow-500' : 'text-green-500'}`}>
            {loading ? '⟳ обновление' : `● ${logs.length} строк`}
          </span>
          <button
            onClick={fetchLogs}
            className="px-3 py-1.5 bg-gray-100 rounded-lg text-sm hover:bg-gray-200 transition-colors"
          >
            Обновить
          </button>
            <button
            onClick={() => {
              const text = visible.map(l => `[${l.t}] ${l.lvl} [${l.name}] ${l.msg}`).join('\n')
              navigator.clipboard.writeText(text)
            }}
            className="px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-sm hover:bg-blue-100 transition-colors"
          >
            Копировать
          </button>
          <button
            onClick={() => setLogs([])}
            className="px-3 py-1.5 bg-red-50 text-red-600 rounded-lg text-sm hover:bg-red-100 transition-colors"
          >
            Очистить
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="flex gap-1">
          {levels.map(lvl => (
            <button
              key={lvl}
              onClick={() => setFilter(lvl)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                filter === lvl ? 'bg-black text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {lvl}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Поиск в логах..."
          className="flex-1 min-w-[200px] border border-gray-200 rounded-lg px-3 py-1 text-sm focus:outline-none focus:border-black"
        />
        <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={e => setAutoScroll(e.target.checked)}
            className="rounded"
          />
          Авто-скролл
        </label>
      </div>

      {/* Log window */}
      <div className="flex-1 bg-gray-950 rounded-xl overflow-auto font-mono text-xs p-3 min-h-0">
        {visible.length === 0 ? (
          <div className="text-gray-500 text-center mt-8">Логов нет</div>
        ) : (
          visible.map((l, i) => (
            <div key={i} className="flex gap-2 py-0.5 border-b border-gray-800 hover:bg-gray-900">
              <span className="text-gray-500 shrink-0 w-16">{l.t}</span>
              <span className={`shrink-0 w-16 ${LVL_COLOR[l.lvl] || 'text-gray-300'}`}>{l.lvl}</span>
              <span className="text-purple-400 shrink-0 w-20 truncate">{l.name}</span>
              <span className="text-gray-200 break-all">{l.msg}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      <div className="text-xs text-gray-400 text-right">
        Показано {visible.length} из {logs.length} строк · обновляется каждые 3 сек
      </div>
    </div>
  )
}
