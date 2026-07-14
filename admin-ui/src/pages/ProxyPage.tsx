import { useCallback, useEffect, useState } from 'react'
import { Network, RefreshCw, Plus, Trash2, Shield, Copy, Check } from 'lucide-react'

type ProxyNode = {
  id: string
  name: string
  role: string
  public_ip: string
  ssh_port: number
  socks_port: number
  socks_user: string
  socks_password?: string
  agent_url?: string | null
  status: string
  is_primary: boolean
  priority: number
  last_error?: string | null
  endpoint?: string | null
  message?: string
}

const statusColor: Record<string, string> = {
  active: 'text-emerald-400',
  provisioning: 'text-blue-400',
  degraded: 'text-amber-400',
  blocked: 'text-red-400',
  error: 'text-red-400',
  pending: 'text-[#888]',
  draining: 'text-orange-400',
}

export default function ProxyPage({ token }: { token: string }) {
  const [nodes, setNodes] = useState<ProxyNode[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState<string | null>(null)
  const [form, setForm] = useState({
    host: '',
    password: '',
    name: '',
    ssh_port: '22',
    role: 'attached' as 'dedicated' | 'attached',
    prefer_socks_port: '',
  })

  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/proxy/nodes', { headers: { Authorization: `Bearer ${token}` } })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setNodes(data.nodes || [])
      setError('')
    } catch (e: any) {
      setError(e.message || 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    load()
    const hasProv = nodes.some((n) => n.status === 'provisioning')
    const t = setInterval(load, hasProv ? 4000 : 12000)
    return () => clearInterval(t)
  }, [load, nodes.some((n) => n.status === 'provisioning')])

  async function connect(e: React.FormEvent) {
    e.preventDefault()
    setBusy('connect')
    setError('')
    try {
      const body: Record<string, unknown> = {
        host: form.host.trim(),
        password: form.password,
        role: form.role,
        ssh_port: parseInt(form.ssh_port || '22', 10) || 22,
      }
      if (form.name.trim()) body.name = form.name.trim()
      if (form.prefer_socks_port.trim()) {
        body.prefer_socks_port = parseInt(form.prefer_socks_port, 10)
      }
      const res = await fetch('/api/admin/proxy/nodes/connect', {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setForm({ host: '', password: '', name: '', ssh_port: '22', role: 'attached', prefer_socks_port: '' })
      await load()
    } catch (e: any) {
      setError(typeof e.message === 'string' ? e.message : 'Ошибка подключения')
    } finally {
      setBusy(null)
    }
  }

  async function probe(id: string) {
    setBusy(id)
    try {
      await fetch(`/api/admin/proxy/nodes/${id}/probe`, { method: 'POST', headers })
      await load()
    } finally {
      setBusy(null)
    }
  }

  async function remove(id: string) {
    if (!confirm('Удалить ноду из админки? На VPS сайт/прокси не трогаем.')) return
    setBusy(id)
    try {
      await fetch(`/api/admin/proxy/nodes/${id}`, { method: 'DELETE', headers })
      await load()
    } finally {
      setBusy(null)
    }
  }

  async function copyEndpoint(id: string) {
    const res = await fetch(`/api/admin/proxy/nodes/${id}/endpoint`, { headers })
    const data = await res.json()
    const ep = data.endpoint || data.socks_password
    if (!ep) return
    await navigator.clipboard.writeText(data.endpoint || '')
    setCopied(id)
    setTimeout(() => setCopied(null), 2000)
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Network className="w-7 h-7" />
            Прокси
          </h1>
          <p className="text-[#888] text-sm mt-1">
            Управление отдельным прокси-флотом (не Улей/VPN). Primary: HTTP + SOCKS5 + MTProto.
            Сайты (attached) по SSH цепляются к primary: снимается только старый proxy, env
            переписывается на этот прокси — не на соты Улья.
          </p>
        </div>
        <button type="button" onClick={() => { setLoading(true); load() }}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-[#1a1a1a] text-sm text-[#aaa] hover:text-white">
          <RefreshCw className="w-4 h-4" /> Обновить
        </button>
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-900 text-red-300 text-sm rounded-lg px-4 py-3">{error}</div>
      )}

      <form onSubmit={connect} className="bg-[#111] border border-[#222] rounded-xl p-5 space-y-4">
        <h2 className="font-semibold flex items-center gap-2">
          <Plus className="w-4 h-4" /> Подключить
        </h2>
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="text-sm text-[#888] space-y-1">
            <span>Host / IP сервера</span>
            <input required value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })}
              className="w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-white" placeholder="vps.example.ru или IP" />
          </label>
          <label className="text-sm text-[#888] space-y-1">
            <span>SSH пароль root</span>
            <input required type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-white" />
          </label>
          <label className="text-sm text-[#888] space-y-1">
            <span>Название (необязательно)</span>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              className="w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-white" placeholder="сайт-1 / proxy-primary" />
          </label>
          <label className="text-sm text-[#888] space-y-1">
            <span>SSH порт (как есть, без автосмены)</span>
            <input value={form.ssh_port} onChange={(e) => setForm({ ...form, ssh_port: e.target.value })}
              className="w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-white" placeholder="22 или 49452" />
          </label>
          <label className="text-sm text-[#888] space-y-1">
            <span>Тип</span>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as any })}
              className="w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-white">
              <option value="dedicated">Proxy-VPS (HTTP+SOCKS+MTProto)</option>
              <option value="attached">Сайт → привязать к primary</option>
            </select>
          </label>
          {form.role === 'dedicated' && (
            <label className="text-sm text-[#888] space-y-1">
              <span>SOCKS-порт (опционально)</span>
              <input value={form.prefer_socks_port} onChange={(e) => setForm({ ...form, prefer_socks_port: e.target.value })}
                className="w-full bg-[#0a0a0a] border border-[#333] rounded-lg px-3 py-2 text-white" placeholder="1080" />
            </label>
          )}
        </div>
        <p className="text-xs text-[#666] flex items-start gap-2">
          <Shield className="w-4 h-4 shrink-0 mt-0.5" />
          Сайт (attached): только whitelist старого proxy + правка .env на primary HTTP/SOCKS.
          Не трогает nginx, PM2-код сайта, /var/www, БД. Улей/VPN не затрагивается.
        </p>
        <button type="submit" disabled={!!busy}
          className="px-4 py-2 rounded-lg bg-white text-black text-sm font-medium disabled:opacity-50">
          {busy === 'connect' ? 'Запуск…' : 'Подключить'}
        </button>
      </form>

      <div className="space-y-3">
        {loading && nodes.length === 0 && <p className="text-[#666] text-sm">Загрузка…</p>}
        {!loading && nodes.length === 0 && (
          <p className="text-[#666] text-sm">Нод пока нет — подключите чистый proxy-VPS.</p>
        )}
        {nodes.map((n) => (
          <div key={n.id} className="bg-[#111] border border-[#222] rounded-xl p-4 flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-medium">{n.name}</span>
                {n.is_primary && <span className="text-xs bg-amber-950 text-amber-300 px-2 py-0.5 rounded">primary</span>}
                <span className="text-xs bg-[#1a1a1a] text-[#888] px-2 py-0.5 rounded">{n.role}</span>
                <span className={`text-xs ${statusColor[n.status] || 'text-[#888]'}`}>{n.status}</span>
              </div>
              <p className="text-sm text-[#888] mt-1">
                {n.public_ip}:{n.socks_port} · user {n.socks_user}
                {n.agent_url ? ` · agent ${n.agent_url}` : ''}
              </p>
              {n.endpoint && <p className="text-xs text-[#555] mt-1 font-mono">{n.endpoint}</p>}
              {n.last_error && (
                <p className="text-xs text-red-400 mt-1 whitespace-pre-wrap break-all max-w-xl">
                  Ошибка: {n.last_error}
                </p>
              )}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button type="button" onClick={() => copyEndpoint(n.id)} disabled={n.status === 'provisioning'}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-xs text-[#aaa] hover:text-white disabled:opacity-40">
                {copied === n.id ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                Endpoint
              </button>
              <button type="button" onClick={() => probe(n.id)} disabled={busy === n.id || !n.agent_url}
                className="px-3 py-1.5 rounded-lg bg-[#1a1a1a] text-xs text-[#aaa] hover:text-white disabled:opacity-40">
                Probe
              </button>
              <button type="button" onClick={() => remove(n.id)} disabled={busy === n.id}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-red-950/40 text-xs text-red-300 hover:bg-red-950">
                <Trash2 className="w-3.5 h-3.5" /> Из админки
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
