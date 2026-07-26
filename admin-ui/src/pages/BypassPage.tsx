import { useCallback, useEffect, useState } from 'react'
import { Loader2, RefreshCw, Save, KeyRound, FileCode2, Plus, Trash2 } from 'lucide-react'
import VkPage from './VkPage'

type RoomSlot = {
  id: string
  url: string
  max_clients: number
  device_types: string[]
}

type ProviderCfg = {
  enabled: boolean
  room: string
  transport: string
  rooms?: RoomSlot[]
}

type OlcrtcSettings = {
  enabled: boolean
  crypto_key: string
  providers: Record<string, ProviderCfg>
  srv_status: string
  srv_message: string
}

const PROVIDER_META: { id: string; title: string; roomHint: string; defaultTransport: string }[] = [
  {
    id: 'telemost',
    title: 'Яндекс Телемост',
    roomHint: 'room-id',
    defaultTransport: 'vp8channel',
  },
  {
    id: 'wbstream',
    title: 'WB Stream',
    roomHint: 'room-id',
    defaultTransport: 'vp8channel',
  },
]

const TRANSPORTS = ['datachannel', 'vp8channel', 'seichannel', 'videochannel']

const DEFAULT_ROOMS: Record<string, RoomSlot[]> = {
  wbstream: [
    {
      id: 'pc',
      url: '',
      max_clients: 4,
      device_types: ['pc'],
    },
    {
      id: 'android',
      url: '',
      max_clients: 4,
      device_types: ['android'],
    },
  ],
  telemost: [
    {
      id: 'pc',
      url: '',
      max_clients: 4,
      device_types: ['pc'],
    },
    {
      id: 'android',
      url: '',
      max_clients: 4,
      device_types: ['android'],
    },
  ],
}

function defaultRoomsFor(id: string): RoomSlot[] {
  return (DEFAULT_ROOMS[id] || []).map((r) => ({ ...r, device_types: [...r.device_types] }))
}

function emptySettings(): OlcrtcSettings {
  return {
    enabled: false,
    crypto_key: '',
    providers: Object.fromEntries(
      PROVIDER_META.map((p) => [
        p.id,
        {
          enabled: false,
          room: '',
          transport: p.defaultTransport,
          rooms: defaultRoomsFor(p.id),
        },
      ]),
    ),
    srv_status: 'unknown',
    srv_message: '',
  }
}

function normalizeProvider(id: string, raw?: Partial<ProviderCfg>): ProviderCfg {
  const meta = PROVIDER_META.find((p) => p.id === id)
  const base: ProviderCfg = {
    enabled: false,
    room: '',
    transport: meta?.defaultTransport || 'datachannel',
    rooms: defaultRoomsFor(id),
  }
  if (!raw) return base
  const rooms =
    Array.isArray(raw.rooms) && raw.rooms.length > 0
      ? raw.rooms.map((r, i) => ({
          id: (r.id || `r${i}`).trim() || `r${i}`,
          url: (r.url || '').trim(),
          max_clients: Math.max(1, Number(r.max_clients) || 4),
          device_types: Array.isArray(r.device_types) ? r.device_types.map(String) : [],
        }))
      : raw.room
        ? [
            {
              id: 'default',
              url: raw.room,
              max_clients: 8,
              device_types: [] as string[],
            },
          ]
        : base.rooms
  return {
    enabled: Boolean(raw.enabled),
    room: (raw.room || rooms?.[0]?.url || '').trim(),
    transport: (raw.transport || base.transport).trim() || base.transport,
    rooms,
  }
}

function OlcrtcSection({ token }: { token: string }) {
  const [cfg, setCfg] = useState<OlcrtcSettings>(emptySettings)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [yamlPreview, setYamlPreview] = useState('')
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const authH = { Authorization: `Bearer ${token}` }
  const jsonH = { ...authH, 'Content-Type': 'application/json' }

  const mergeSettings = (data: Partial<OlcrtcSettings>): OlcrtcSettings => {
    const empty = emptySettings()
    const providers: Record<string, ProviderCfg> = { ...empty.providers }
    for (const meta of PROVIDER_META) {
      providers[meta.id] = normalizeProvider(meta.id, data.providers?.[meta.id])
    }
    return {
      ...empty,
      ...data,
      providers,
    }
  }

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      const res = await fetch('/api/admin/bypass/olcrtc', { headers: authH })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = (await res.json()) as OlcrtcSettings
      setCfg(mergeSettings(data))
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  const save = async () => {
    setSaving(true)
    setMsg('')
    setErr('')
    try {
      const res = await fetch('/api/admin/bypass/olcrtc', {
        method: 'PUT',
        headers: jsonH,
        body: JSON.stringify({
          enabled: cfg.enabled,
          crypto_key: cfg.crypto_key,
          providers: cfg.providers,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setCfg(mergeSettings(data))
      const r = data.reconcile as
        | { updated?: number; created?: number; changed_units?: string[] }
        | undefined
      if (r && (r.updated || r.created)) {
        setMsg(
          `Сохранено → БД комнат обновлена (upd=${r.updated || 0}, new=${r.created || 0}). ` +
            `Дальше: «Записать YAML» + python scripts/apply_olcrtc_units_from_db.py — иначе srv сидит на старом канале.`,
        )
      } else {
        setMsg('Сохранено')
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const generateKey = async () => {
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/bypass/olcrtc/generate-key', {
        method: 'POST',
        headers: authH,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      if (data.settings) {
        setCfg(mergeSettings(data.settings))
      } else if (data.crypto_key) {
        setCfg((c) => ({ ...c, crypto_key: data.crypto_key }))
      }
      setMsg('Новый crypto.key сгенерирован и сохранён')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка генерации')
    }
  }

  const previewYaml = async () => {
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/bypass/olcrtc/server-yaml', { headers: authH })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      if (data.files && typeof data.files === 'object') {
        const parts = Object.entries(data.files as Record<string, string>).map(
          ([id, text]) => `=== ${id === 'default' ? 'server.yaml' : `server-${id}.yaml`} ===\n${text}`,
        )
        setYamlPreview(parts.join('\n\n'))
      } else {
        setYamlPreview(data.yaml || '')
      }
      setMsg('YAML превью обновлено (пул комнат)')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка YAML')
    }
  }

  const applyYaml = async () => {
    setErr('')
    setMsg('')
    setSaving(true)
    try {
      const res = await fetch('/api/admin/bypass/olcrtc/apply', {
        method: 'POST',
        headers: authH,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      if (data.settings) setCfg(mergeSettings(data.settings))
      setMsg(data.message || 'YAML записан — запустите deploy_olcrtc.py')
      await previewYaml()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка apply')
    } finally {
      setSaving(false)
    }
  }

  const setProvider = (id: string, patch: Partial<ProviderCfg>) => {
    setCfg((c) => ({
      ...c,
      providers: {
        ...c.providers,
        [id]: { ...c.providers[id], ...patch },
      },
    }))
  }

  const setRoom = (providerId: string, index: number, patch: Partial<RoomSlot>) => {
    setCfg((c) => {
      const p = c.providers[providerId]
      const rooms = [...(p.rooms || [])]
      rooms[index] = { ...rooms[index], ...patch }
      const room = rooms[0]?.url || p.room
      return {
        ...c,
        providers: {
          ...c.providers,
          [providerId]: { ...p, rooms, room },
        },
      }
    })
  }

  const addRoom = (providerId: string) => {
    setCfg((c) => {
      const p = c.providers[providerId]
      const rooms = [
        ...(p.rooms || []),
        {
          id: `r${(p.rooms || []).length + 1}`,
          url: '',
          max_clients: 4,
          device_types: [] as string[],
        },
      ]
      return {
        ...c,
        providers: { ...c.providers, [providerId]: { ...p, rooms } },
      }
    })
  }

  const removeRoom = (providerId: string, index: number) => {
    setCfg((c) => {
      const p = c.providers[providerId]
      const rooms = (p.rooms || []).filter((_, i) => i !== index)
      return {
        ...c,
        providers: {
          ...c.providers,
          [providerId]: { ...p, rooms, room: rooms[0]?.url || '' },
        },
      }
    })
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[#888] text-sm py-8">
        <Loader2 className="w-4 h-4 animate-spin" /> Загрузка olcrtc…
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-white cursor-pointer">
          <input
            type="checkbox"
            checked={cfg.enabled}
            onChange={(e) => setCfg((c) => ({ ...c, enabled: e.target.checked }))}
            className="rounded border-[#333]"
          />
          Вариант 2 включён (отдавать конфиг клиентам)
        </label>
        <span className="text-xs text-[#666]">
          srv: <span className="text-[#aaa]">{cfg.srv_status || 'unknown'}</span>
        </span>
        <button
          type="button"
          onClick={load}
          className="text-xs text-[#888] hover:text-white flex items-center gap-1"
        >
          <RefreshCw className="w-3 h-3" /> Обновить
        </button>
      </div>

      {cfg.srv_message ? (
        <p className="text-xs text-[#888] break-all">{cfg.srv_message}</p>
      ) : null}

      <div>
        <div className="flex items-center justify-between gap-2 mb-1">
          <label className="text-xs text-[#888]">crypto.key (64 hex)</label>
          <button
            type="button"
            onClick={generateKey}
            className="text-xs flex items-center gap-1 text-[#aaa] hover:text-white"
          >
            <KeyRound className="w-3 h-3" /> Сгенерировать
          </button>
        </div>
        <input
          value={cfg.crypto_key}
          onChange={(e) => setCfg((c) => ({ ...c, crypto_key: e.target.value.trim() }))}
          className="w-full bg-[#111] border border-[#222] rounded-lg px-3 py-2 text-sm font-mono text-white"
          placeholder="openssl rand -hex 32"
          spellCheck={false}
        />
      </div>

      <div className="space-y-4">
        {PROVIDER_META.map((meta) => {
          const p = cfg.providers[meta.id] || normalizeProvider(meta.id)
          const rooms = p.rooms && p.rooms.length > 0 ? p.rooms : []
          return (
            <div
              key={meta.id}
              className="border border-[#222] rounded-xl p-4 bg-[#0d0d0d] space-y-3"
            >
              <label className="flex items-center gap-2 text-sm text-white cursor-pointer">
                <input
                  type="checkbox"
                  checked={p.enabled}
                  onChange={(e) => setProvider(meta.id, { enabled: e.target.checked })}
                />
                {meta.title}
              </label>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-[#888]">
                    Пул комнат → <code className="text-[#aaa]">olcrtc@slot</code>. PC и Android —
                    разные room id (не шарить одну комнату).
                  </p>
                  <button
                    type="button"
                    onClick={() => addRoom(meta.id)}
                    className="text-xs flex items-center gap-1 text-[#aaa] hover:text-white"
                  >
                    <Plus className="w-3 h-3" /> Комната
                  </button>
                </div>
                {rooms.map((r, idx) => (
                  <div
                    key={`${r.id}-${idx}`}
                    className="border border-[#1a1a1a] rounded-lg p-3 space-y-2 bg-[#0a0a0a]"
                  >
                    <div className="flex flex-wrap gap-2">
                      <div className="w-28">
                        <label className="text-[10px] text-[#666]">slot id</label>
                        <input
                          value={r.id}
                          onChange={(e) => setRoom(meta.id, idx, { id: e.target.value.trim() })}
                          className="w-full mt-0.5 bg-[#111] border border-[#222] rounded px-2 py-1.5 text-xs font-mono text-white"
                          placeholder="pc"
                        />
                      </div>
                      <div className="w-20">
                        <label className="text-[10px] text-[#666]">max</label>
                        <input
                          type="number"
                          min={1}
                          value={r.max_clients}
                          onChange={(e) =>
                            setRoom(meta.id, idx, {
                              max_clients: Math.max(1, Number(e.target.value) || 4),
                            })
                          }
                          className="w-full mt-0.5 bg-[#111] border border-[#222] rounded px-2 py-1.5 text-xs text-white"
                        />
                      </div>
                      <div className="flex-1 min-w-[140px]">
                        <label className="text-[10px] text-[#666]">
                          device_types (через запятую)
                        </label>
                        <input
                          value={(r.device_types || []).join(',')}
                          onChange={(e) =>
                            setRoom(meta.id, idx, {
                              device_types: e.target.value
                                .split(',')
                                .map((x) => x.trim().toLowerCase())
                                .filter(Boolean),
                            })
                          }
                          className="w-full mt-0.5 bg-[#111] border border-[#222] rounded px-2 py-1.5 text-xs text-white"
                          placeholder="pc или android"
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => removeRoom(meta.id, idx)}
                        className="self-end p-1.5 text-[#666] hover:text-red-400"
                        title="Удалить"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div>
                      <label className="text-[10px] text-[#666]">
                        Room ID / URL
                      </label>
                      <input
                        value={r.url}
                        onChange={(e) => setRoom(meta.id, idx, { url: e.target.value })}
                        className="w-full mt-0.5 bg-[#111] border border-[#222] rounded-lg px-3 py-2 text-sm text-white"
                        placeholder={meta.roomHint}
                      />
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <label className="text-xs text-[#888]">Transport</label>
                <select
                  value={p.transport}
                  onChange={(e) => setProvider(meta.id, { transport: e.target.value })}
                  className="w-full mt-1 bg-[#111] border border-[#222] rounded-lg px-3 py-2 text-sm text-white"
                >
                  {TRANSPORTS.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-white text-black text-sm font-medium disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          Сохранить
        </button>
        <button
          type="button"
          onClick={previewYaml}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-[#333] text-sm text-[#ccc] hover:text-white"
        >
          <FileCode2 className="w-4 h-4" /> Превью YAML
        </button>
        <button
          type="button"
          onClick={applyYaml}
          disabled={saving}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-[#444] text-sm text-[#ccc] hover:text-white disabled:opacity-50"
        >
          Записать YAML (для deploy)
        </button>
      </div>

      <p className="text-xs text-[#666]">
        Смена канала Telemost/WB: <b>Сохранить</b> (пишет в БД пула) → «Записать YAML» → на
        Windows{' '}
        <code className="text-[#888]">
          cd backend; python scripts/apply_olcrtc_units_from_db.py
        </code>{' '}
        (рестарт unit’ов). Без apply клиент может получить новый room id, а peer на сервере — старый.
      </p>

      {yamlPreview ? (
        <pre className="text-xs bg-[#111] border border-[#222] rounded-lg p-3 overflow-auto text-[#9f9] max-h-80 whitespace-pre-wrap">
          {yamlPreview}
        </pre>
      ) : null}

      {msg ? <p className="text-sm text-emerald-400">{msg}</p> : null}
      {err ? <p className="text-sm text-red-400">{err}</p> : null}

      <PoolRoomsSection token={token} />
      <RoomAgentSection token={token} />
    </div>
  )
}

type PoolRoom = {
  id: string
  provider: string
  room_url: string
  slot_label: string
  unit_name: string
  status: string
  max_clients: number
  online_count: number
  headroom: number
  cell_id: string | null
}

type PoolMetrics = {
  rooms_active: number
  online_total: number
  capacity_total: number
  free_slots: number
  fill_ratio: number
}

function PoolRoomsSection({ token }: { token: string }) {
  const [rooms, setRooms] = useState<PoolRoom[]>([])
  const [metrics, setMetrics] = useState<PoolMetrics | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const authH = { Authorization: `Bearer ${token}` }

  const load = useCallback(async () => {
    setErr('')
    try {
      const res = await fetch('/api/admin/bypass/olcrtc/rooms', { headers: authH })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRooms(data.rooms || [])
      setMetrics(data.metrics || null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка пула')
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  const setStatus = async (id: string, status: string) => {
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch(`/api/admin/bypass/olcrtc/rooms/${id}/status`, {
        method: 'POST',
        headers: { ...authH, 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setMsg(`status → ${status}`)
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border border-[#222] rounded-xl p-4 bg-[#0d0d0d] space-y-3 mt-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-white">Пул комнат (1000+ / Улей)</h3>
        <button
          type="button"
          onClick={load}
          className="text-xs text-[#888] hover:text-white flex items-center gap-1"
        >
          <RefreshCw className="w-3 h-3" /> Обновить
        </button>
      </div>
      <p className="text-xs text-[#666]">
        Это общий пул, не «комната на одного пользователя». Колонка online — сколько
        клиентов сейчас сидят на комнате / лимит (например 0/25 = никто онлайн, до 25
        одновременно). Telemost/WB
        обычно 1–2 на платформу. Sticky + draining. Unit:{' '}
        <code className="text-[#888]">olcrtc@unit_name</code>.
      </p>
      {metrics ? (
        <p className="text-xs text-[#aaa]">
          active {metrics.rooms_active} · online {metrics.online_total}/
          {metrics.capacity_total} · free {metrics.free_slots} · fill{' '}
          {Math.round((metrics.fill_ratio || 0) * 100)}%
        </p>
      ) : null}
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-left">
          <thead className="text-[#666]">
            <tr>
              <th className="py-1 pr-2">unit</th>
              <th className="py-1 pr-2">prov</th>
              <th className="py-1 pr-2" title="сейчас онлайн / max одновременных на эту комнату">
                online/max
              </th>
              <th className="py-1 pr-2">status</th>
              <th className="py-1 pr-2">room</th>
              <th className="py-1">actions</th>
            </tr>
          </thead>
          <tbody>
            {rooms.map((r) => (
              <tr key={r.id} className="border-t border-[#1a1a1a] text-[#ccc]">
                <td className="py-1.5 pr-2 font-mono text-[10px]">{r.unit_name}</td>
                <td className="py-1.5 pr-2">{r.provider}</td>
                <td className="py-1.5 pr-2">
                  {r.online_count}/{r.max_clients}
                </td>
                <td className="py-1.5 pr-2">{r.status}</td>
                <td className="py-1.5 pr-2 font-mono text-[10px] max-w-[160px] truncate">
                  {r.room_url}
                </td>
                <td className="py-1.5 space-x-1 whitespace-nowrap">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setStatus(r.id, 'draining')}
                    className="text-[10px] text-amber-400 hover:underline"
                  >
                    drain
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setStatus(r.id, 'active')}
                    className="text-[10px] text-emerald-400 hover:underline"
                  >
                    active
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setStatus(r.id, 'offline')}
                    className="text-[10px] text-[#888] hover:underline"
                  >
                    off
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rooms.length === 0 ? (
        <p className="text-xs text-[#666]">Пул пуст — сохрани провайдеры и Apply, или sync при старте API.</p>
      ) : null}
      {msg ? <p className="text-sm text-emerald-400">{msg}</p> : null}
      {err ? <p className="text-sm text-red-400">{err}</p> : null}
    </div>
  )
}

type AgentInfo = {
  enabled: boolean
  last_run_at: string
  last_error: string
  last_ok: string
  run_log: string[]
  auto_apply_yaml: boolean
  playwright_available: boolean
  target_rooms_telemost?: number
  target_rooms_wbstream?: number
  target_capacity?: number
}

type HostProvisionInfo = {
  reachable?: boolean
  playwright?: boolean
  telemost_state?: boolean
  wbstream_state?: boolean
  url?: string
  error?: string
}

type AccountsPublic = {
  telemost: { label: string; configured: boolean; storage_state_path: string; notes: string }[]
  wbstream: { label: string; configured: boolean; storage_state_path: string; notes: string }[]
}

function RoomAgentSection({ token }: { token: string }) {
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [accounts, setAccounts] = useState<AccountsPublic | null>(null)
  const [hostProv, setHostProv] = useState<HostProvisionInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [tmPath, setTmPath] = useState('')
  const [wbPath, setWbPath] = useState('')
  const [tmJson, setTmJson] = useState('')
  const [wbJson, setWbJson] = useState('')

  const authH = { Authorization: `Bearer ${token}` }
  const jsonH = { ...authH, 'Content-Type': 'application/json' }

  const load = useCallback(async () => {
    setErr('')
    try {
      const res = await fetch('/api/admin/bypass/olcrtc/room-agent', { headers: authH })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setAgent(data.agent)
      setAccounts(data.accounts)
      setHostProv(data.host_provision || null)
      const tm = data.accounts?.telemost?.[0]
      const wb = data.accounts?.wbstream?.[0]
      if (tm?.storage_state_path) setTmPath(tm.storage_state_path)
      if (wb?.storage_state_path) setWbPath(wb.storage_state_path)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка агента')
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  const setEnabled = async (enabled: boolean) => {
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/bypass/olcrtc/room-agent', {
        method: 'PUT',
        headers: jsonH,
        body: JSON.stringify({ enabled }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setAgent(data.agent)
      setMsg(enabled ? 'Агент включён' : 'Агент выключен')
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  const runNow = async () => {
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch('/api/admin/bypass/olcrtc/room-agent/run', {
        method: 'POST',
        headers: authH,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setAgent(data.agent)
      setMsg(data.message || 'Heal запущен')
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка run')
    } finally {
      setBusy(false)
    }
  }

  const saveAccounts = async () => {
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      let tmState: Record<string, unknown> | undefined
      let wbState: Record<string, unknown> | undefined
      if (tmJson.trim()) {
        tmState = JSON.parse(tmJson) as Record<string, unknown>
      }
      if (wbJson.trim()) {
        wbState = JSON.parse(wbJson) as Record<string, unknown>
      }
      const res = await fetch('/api/admin/bypass/olcrtc/room-accounts', {
        method: 'PUT',
        headers: jsonH,
        body: JSON.stringify({
          telemost: [
            {
              label: 'primary',
              storage_state_path: tmPath.trim(),
              storage_state: tmState || {},
              notes: '',
            },
          ],
          wbstream: [
            {
              label: 'primary',
              storage_state_path: wbPath.trim(),
              storage_state: wbState || {},
              notes: '',
            },
          ],
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      setAccounts(data.accounts)
      setTmJson('')
      setWbJson('')
      setMsg('Аккаунты сохранены (cookies не показываются обратно)')
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Ошибка сохранения аккаунтов')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border border-[#222] rounded-xl p-4 bg-[#0d0d0d] space-y-3 mt-8">
      <h3 className="text-sm font-medium text-white">Агент комнат (Телемост + WB)</h3>
      <p className="text-xs text-[#666]">
        Создаёт комнаты Телемост/WB через host Playwright (Chromium на Улье) и один раз
        сохранённый storage_state. Не регистрирует аккаунты. Цель — target_rooms (по умолчанию
        4 на провайдера). После peer dead — heal/пересоздание.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-white cursor-pointer">
          <input
            type="checkbox"
            checked={Boolean(agent?.enabled)}
            onChange={(e) => setEnabled(e.target.checked)}
            disabled={busy}
          />
          Агент включён (цикл ~30 мин)
        </label>
        <span className="text-xs text-[#666]">
          host:{' '}
          <span className={hostProv?.reachable ? 'text-emerald-400' : 'text-amber-400'}>
            {hostProv?.reachable
              ? `ok${hostProv.playwright ? '+pw' : ' (нет chromium)'} tm=${hostProv.telemost_state ? '1' : '0'} wb=${hostProv.wbstream_state ? '1' : '0'}`
              : hostProv?.error || 'недоступен — deploy_olcrtc_host_provision.py'}
          </span>
        </span>
        <span className="text-xs text-[#666]">
          docker-pw:{' '}
          <span className={agent?.playwright_available ? 'text-emerald-400' : 'text-[#555]'}>
            {agent?.playwright_available ? 'ok' : 'нет'}
          </span>
        </span>
        <button
          type="button"
          onClick={runNow}
          disabled={busy}
          className="text-xs px-3 py-1.5 rounded border border-[#333] text-[#ccc] hover:text-white disabled:opacity-50"
        >
          Создать недостающие сейчас
        </button>
        <button
          type="button"
          onClick={load}
          className="text-xs text-[#888] hover:text-white flex items-center gap-1"
        >
          <RefreshCw className="w-3 h-3" /> Обновить
        </button>
      </div>

      {agent?.last_error ? (
        <p className="text-xs text-amber-400 break-all">{agent.last_error}</p>
      ) : null}
      {agent?.last_run_at ? (
        <p className="text-[10px] text-[#555]">
          last run: {agent.last_run_at}
          {agent.last_ok ? ` · last ok: ${agent.last_ok}` : ''}
        </p>
      ) : null}

      <div className="grid md:grid-cols-2 gap-3">
        <div className="space-y-2">
          <label className="text-xs text-[#888]">Telemost: путь storage_state на сервере</label>
          <input
            value={tmPath}
            onChange={(e) => setTmPath(e.target.value)}
            className="w-full bg-[#111] border border-[#222] rounded px-2 py-1.5 text-xs font-mono text-white"
            placeholder="/opt/silent-vpn/olcrtc/telemost_state.json"
          />
          <label className="text-xs text-[#888]">или вставить JSON storage_state</label>
          <textarea
            value={tmJson}
            onChange={(e) => setTmJson(e.target.value)}
            rows={3}
            className="w-full bg-[#111] border border-[#222] rounded px-2 py-1.5 text-xs font-mono text-white"
            placeholder='{"cookies":[...],"origins":[...]}'
          />
          <p className="text-[10px] text-[#555]">
            configured: {accounts?.telemost?.[0]?.configured ? 'yes' : 'no'}
          </p>
        </div>
        <div className="space-y-2">
          <label className="text-xs text-[#888]">WB Stream: путь storage_state</label>
          <input
            value={wbPath}
            onChange={(e) => setWbPath(e.target.value)}
            className="w-full bg-[#111] border border-[#222] rounded px-2 py-1.5 text-xs font-mono text-white"
            placeholder="/opt/silent-vpn/olcrtc/wbstream_state.json"
          />
          <label className="text-xs text-[#888]">или вставить JSON storage_state</label>
          <textarea
            value={wbJson}
            onChange={(e) => setWbJson(e.target.value)}
            rows={3}
            className="w-full bg-[#111] border border-[#222] rounded px-2 py-1.5 text-xs font-mono text-white"
            placeholder='{"cookies":[...],"origins":[...]}'
          />
          <p className="text-[10px] text-[#555]">
            configured: {accounts?.wbstream?.[0]?.configured ? 'yes' : 'no'}
          </p>
        </div>
      </div>

      <button
        type="button"
        onClick={saveAccounts}
        disabled={busy}
        className="text-xs px-3 py-1.5 rounded bg-[#1a1a1a] border border-[#333] text-[#ccc] hover:text-white disabled:opacity-50"
      >
        Сохранить аккаунты агента
      </button>

      {agent?.run_log && agent.run_log.length > 0 ? (
        <pre className="text-[10px] bg-[#111] border border-[#222] rounded p-2 max-h-40 overflow-auto text-[#888]">
          {agent.run_log.join('\n')}
        </pre>
      ) : null}

      {msg ? <p className="text-sm text-emerald-400">{msg}</p> : null}
      {err ? <p className="text-sm text-red-400">{err}</p> : null}
    </div>
  )
}

export default function BypassPage({ token }: { token: string }) {
  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-xl font-semibold text-white mb-1">Варианты обхода</h1>
        <p className="text-sm text-[#888]">
          Вариант 1 — VK / WDTT (как раньше). Вариант 2 — olcrtc (Телемост / WB Stream),
          debug-клиенты. Пул комнат — PC и телефон не в одной комнате.
        </p>
      </div>

      <section className="space-y-4">
        <h2 className="text-lg font-medium text-white border-b border-[#222] pb-2">
          1. VK / WDTT
        </h2>
        <VkPage token={token} />
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-medium text-white border-b border-[#222] pb-2">
          2. olcrtc
        </h2>
        <OlcrtcSection token={token} />
      </section>
    </div>
  )
}
