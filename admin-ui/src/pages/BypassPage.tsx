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
    id: 'jitsi',
    title: 'Jitsi Meet',
    roomHint: 'https://meet.egovm.ru/SilentVpnOlcrtcHive…',
    defaultTransport: 'datachannel',
  },
  {
    id: 'wbstream',
    title: 'WB Stream',
    roomHint: 'room-id',
    defaultTransport: 'vp8channel',
  },
  {
    id: 'telemost',
    title: 'Яндекс Телемост',
    roomHint: 'room-id',
    defaultTransport: 'vp8channel',
  },
]

const TRANSPORTS = ['datachannel', 'vp8channel', 'seichannel', 'videochannel']

const DEFAULT_JITSI_ROOMS: RoomSlot[] = [
  {
    id: 'pc',
    url: 'https://meet.egovm.ru/SilentVpnOlcrtcHive',
    max_clients: 4,
    device_types: ['pc'],
  },
  {
    id: 'android',
    url: 'https://meet.playform.ru/SilentVpnOlcrtcHiveAndroid',
    max_clients: 4,
    device_types: ['android'],
  },
]

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
          rooms: p.id === 'jitsi' ? DEFAULT_JITSI_ROOMS.map((r) => ({ ...r })) : [],
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
    rooms: id === 'jitsi' ? DEFAULT_JITSI_ROOMS.map((r) => ({ ...r })) : [],
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
      setMsg('Сохранено')
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

              {meta.id === 'jitsi' ? (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-[#888]">
                      Пул комнат (отдельный <code className="text-[#aaa]">olcrtc@slot</code> на
                      сервере). PC и Android — разные комнаты.
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
                        <label className="text-[10px] text-[#666]">URL комнаты</label>
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
              ) : (
                <div>
                  <label className="text-xs text-[#888]">Room / URL</label>
                  <input
                    value={p.room}
                    onChange={(e) => setProvider(meta.id, { room: e.target.value })}
                    className="w-full mt-1 bg-[#111] border border-[#222] rounded-lg px-3 py-2 text-sm text-white"
                    placeholder={meta.roomHint}
                  />
                </div>
              )}

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
        После «Записать YAML»: на Windows{' '}
        <code className="text-[#888]">cd backend; python scripts/deploy_olcrtc.py</code> — бинарь +
        systemd <code className="text-[#888]">olcrtc@pc</code> /{' '}
        <code className="text-[#888]">olcrtc@android</code> на Улье.
      </p>

      {yamlPreview ? (
        <pre className="text-xs bg-[#111] border border-[#222] rounded-lg p-3 overflow-auto text-[#9f9] max-h-80 whitespace-pre-wrap">
          {yamlPreview}
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
          Вариант 1 — VK / WDTT (как раньше). Вариант 2 — olcrtc (Jitsi / WB Stream / Телемост),
          debug-клиенты. Jitsi: пул комнат — PC и телефон не в одной комнате.
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
