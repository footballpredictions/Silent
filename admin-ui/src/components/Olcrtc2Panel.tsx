import { useCallback, useEffect, useState } from 'react'

type AgentInfo = {
  enabled?: boolean
  agent_enabled?: boolean
  session_mode?: boolean
  warm_pool_per_dt?: number
  pool?: {
    rooms?: number
    active?: number
    online?: number
    provisioning?: number
    error?: number
    warm_free_pc?: number
    warm_free_android?: number
  }
  cell_ip?: string
  cells?: { telemost?: string; wbstream?: string }
  provider?: string
}

type Settings = {
  enabled: boolean
  agent_enabled: boolean
  provider: string
  room: string
  crypto_key: string
  socks_port: number
  cell_ip: string
  cell_ip_wbstream: string
  cell_provision_url: string
  transport: string
  warm_pool_per_dt: number
  target_online: number
  providers_enabled: string[]
  agent?: AgentInfo
}

const empty: Settings = {
  enabled: false,
  agent_enabled: true,
  provider: 'telemost',
  room: '',
  crypto_key: '',
  socks_port: 8808,
  cell_ip: '87.58.213.193',
  cell_ip_wbstream: '78.17.74.27',
  cell_provision_url: 'http://87.58.213.193:9101',
  transport: 'vp8channel',
  warm_pool_per_dt: 20,
  target_online: 150,
  providers_enabled: ['telemost', 'wbstream'],
}

export default function Olcrtc2Panel({ token }: { token: string }) {
  const [s, setS] = useState<Settings>(empty)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadOk, setLoadOk] = useState(false)
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/admin/olcrtc2', { headers: { Authorization: `Bearer ${token}` } })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const { agent, ...flags } = data || {}
      // Только продуктовые поля — не размазывать agent.* по state
      setS({
        ...empty,
        enabled: !!flags.enabled,
        agent_enabled: flags.agent_enabled !== false,
        provider: flags.provider || 'telemost',
        room: flags.room || '',
        crypto_key: flags.crypto_key || '',
        socks_port: Number(flags.socks_port || 8808),
        cell_ip: flags.cell_ip || flags.cells?.telemost || empty.cell_ip,
        cell_ip_wbstream: flags.cells?.wbstream || empty.cell_ip_wbstream,
        cell_provision_url: flags.cell_provision_url || empty.cell_provision_url,
        transport: flags.transport || 'vp8channel',
        warm_pool_per_dt: Number(flags.warm_pool_per_dt ?? 20),
        target_online: Number(flags.target_online ?? 150),
        providers_enabled: Array.isArray(flags.providers_enabled) && flags.providers_enabled.length
          ? flags.providers_enabled
          : empty.providers_enabled,
        agent: agent || undefined,
      })
      setLoadOk(true)
      setMsg('')
    } catch (e: any) {
      setLoadOk(false)
      setMsg(e?.message || 'load failed')
    }
  }, [token])

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  const save = async (extra?: Partial<Settings> & { generate_key?: boolean }) => {
    if (!loadOk) {
      setMsg('Сначала «Обновить» — настройки не загружены (иначе можно случайно выключить продукт)')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const body: Record<string, unknown> = {
        enabled: s.enabled,
        agent_enabled: s.agent_enabled,
        provider: s.provider,
        room: s.room,
        crypto_key: s.crypto_key,
        socks_port: s.socks_port,
        cell_ip: s.cell_ip,
        cell_ip_wbstream: s.cell_ip_wbstream,
        cell_provision_url: s.cell_provision_url,
        cells: { telemost: s.cell_ip, wbstream: s.cell_ip_wbstream },
        providers_enabled: s.providers_enabled,
        transport: s.transport,
        warm_pool_per_dt: s.warm_pool_per_dt,
        target_online: s.target_online,
        ...extra,
      }
      delete body.agent
      const res = await fetch('/api/admin/olcrtc2', {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`)
      const { agent, ...flags } = data || {}
      setS({
        ...empty,
        enabled: !!flags.enabled,
        agent_enabled: flags.agent_enabled !== false,
        provider: flags.provider || 'telemost',
        room: flags.room || '',
        crypto_key: flags.crypto_key || '',
        socks_port: Number(flags.socks_port || 8808),
        cell_ip: flags.cell_ip || flags.cells?.telemost || empty.cell_ip,
        cell_ip_wbstream: flags.cells?.wbstream || empty.cell_ip_wbstream,
        cell_provision_url: flags.cell_provision_url || empty.cell_provision_url,
        transport: flags.transport || 'vp8channel',
        warm_pool_per_dt: Number(flags.warm_pool_per_dt ?? 20),
        target_online: Number(flags.target_online ?? 150),
        providers_enabled: Array.isArray(flags.providers_enabled) && flags.providers_enabled.length
          ? flags.providers_enabled
          : empty.providers_enabled,
        agent: agent || undefined,
      })
      setLoadOk(true)
      setMsg(
        flags.enabled
          ? 'Сохранено (olcrtc2 ВКЛ)'
          : 'Сохранено — ВНИМАНИЕ: olcrtc2 ВЫКЛ, клиенты получат disabled',
      )
    } catch (e: any) {
      setMsg(e?.message || 'save failed')
    } finally {
      setBusy(false)
    }
  }

  const applyCell = async () => {
    setBusy(true)
    setMsg('')
    try {
      const res = await fetch('/api/admin/olcrtc2/apply-cell', {
        method: 'POST',
        headers,
        body: '{}',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`)
      setMsg(data?.ok ? `Diag сота: ${data.message}` : `Ошибка: ${data?.message || 'fail'}`)
      if (data?.detail) setMsg((m) => `${m}\n${String(data.detail).slice(0, 400)}`)
    } catch (e: any) {
      setMsg(e?.message || 'apply failed')
    } finally {
      setBusy(false)
    }
  }

  const pool = s.agent?.pool

  return (
    <div className="rounded-xl border border-white/10 bg-[#141414] p-5 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-white">olcrtc 2.0 — продукт (session-mode + warm)</h2>
        <p className="text-sm text-[#888] mt-1">
          Агент держит запас пустых комнат на <b className="text-[#aaa]">соте</b>. Connect берёт готовую.
          Цель — до 150 онлайн на WB и на Телемост (не все сразу: запас пополняется по мере входа).
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-xs text-[#ccc]">
        <div className="rounded-lg bg-black/30 p-2">Комнат: {pool?.rooms ?? '—'}</div>
        <div className="rounded-lg bg-black/30 p-2">Active: {pool?.active ?? '—'}</div>
        <div className="rounded-lg bg-black/30 p-2">Online: {pool?.online ?? '—'}</div>
        <div className="rounded-lg bg-black/30 p-2">
          Warm PC: {pool?.warm_free_pc ?? '—'}
        </div>
        <div className="rounded-lg bg-black/30 p-2">
          Warm Android: {pool?.warm_free_android ?? '—'}
        </div>
      </div>

      <label className="flex items-center gap-3 text-sm text-white cursor-pointer">
        <input
          type="checkbox"
          checked={s.enabled}
          onChange={(e) => setS({ ...s, enabled: e.target.checked })}
          className="rounded"
        />
        Включён для клиентов (debug → потом release)
      </label>

      <label className="flex items-center gap-3 text-sm text-white cursor-pointer">
        <input
          type="checkbox"
          checked={s.agent_enabled}
          onChange={(e) => setS({ ...s, agent_enabled: e.target.checked })}
          className="rounded"
        />
        Агент: warm-пул + prune (не рвёт свободные в пределах запаса)
      </label>

      <div className="flex flex-wrap gap-4 text-sm text-white">
        <span className="text-xs text-[#aaa] self-center">Warm провайдеры:</span>
        {(['telemost', 'wbstream'] as const).map((p) => {
          const on = s.providers_enabled.includes(p)
          return (
            <label key={p} className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={on}
                onChange={() => {
                  const next = on
                    ? s.providers_enabled.filter((x) => x !== p)
                    : [...s.providers_enabled, p]
                  setS({
                    ...s,
                    providers_enabled: next.length ? next : [p],
                  })
                }}
                className="rounded"
              />
              {p === 'telemost' ? 'Телемост (Сота 1)' : 'WB Stream (Сота 2)'}
            </label>
          )
        })}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs text-[#aaa] space-y-1">
          Запас пустых комнат (PC и Android отдельно)
          <input
            type="number"
            min={0}
            max={40}
            className="w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white"
            value={s.warm_pool_per_dt}
            onChange={(e) => setS({ ...s, warm_pool_per_dt: Number(e.target.value || 0) })}
          />
        </label>
        <label className="text-xs text-[#aaa] space-y-1">
          Цель онлайн на провайдера (WB / Телемост)
          <input
            type="number"
            min={0}
            max={1000}
            className="w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white"
            value={s.target_online}
            onChange={(e) => setS({ ...s, target_online: Number(e.target.value || 0) })}
          />
        </label>
        <label className="text-xs text-[#aaa] space-y-1">
          Сота Telemost (IP)
          <input
            className="w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white"
            value={s.cell_ip}
            onChange={(e) => setS({ ...s, cell_ip: e.target.value })}
            placeholder="87.58.213.193"
          />
        </label>
        <label className="text-xs text-[#aaa] space-y-1">
          Сота WB (IP)
          <input
            className="w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white"
            value={s.cell_ip_wbstream}
            onChange={(e) => setS({ ...s, cell_ip_wbstream: e.target.value })}
            placeholder="78.17.74.27"
          />
        </label>
        <label className="text-xs text-[#aaa] space-y-1 sm:col-span-2">
          Create URL Telemost (:9101)
          <input
            className="w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white font-mono"
            value={s.cell_provision_url}
            onChange={(e) => setS({ ...s, cell_provision_url: e.target.value })}
            placeholder="http://87.58.213.193:9101"
          />
        </label>
        <label className="text-xs text-[#aaa] space-y-1 sm:col-span-2">
          Master crypto key (fallback; сессиям выдаются свои)
          <div className="flex gap-2">
            <input
              className="flex-1 rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white font-mono"
              value={s.crypto_key}
              onChange={(e) => setS({ ...s, crypto_key: e.target.value })}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => save({ generate_key: true })}
              className="px-3 py-2 rounded-lg bg-white/10 text-sm text-white hover:bg-white/15"
            >
              Сгенерировать
            </button>
          </div>
        </label>
        <label className="text-xs text-[#aaa] space-y-1 sm:col-span-2">
          Diag Room ID (необязательно — только без агента)
          <input
            className="w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white"
            value={s.room}
            onChange={(e) => setS({ ...s, room: e.target.value })}
            placeholder="ручная комната только для отладки"
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => save()}
          className="px-4 py-2 rounded-lg bg-purple-600 text-sm text-white hover:bg-purple-500 disabled:opacity-50"
        >
          Сохранить
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={applyCell}
          className="px-4 py-2 rounded-lg bg-emerald-700 text-sm text-white hover:bg-emerald-600 disabled:opacity-50"
        >
          Diag: apply static room на соту
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={load}
          className="px-4 py-2 rounded-lg bg-white/10 text-sm text-white hover:bg-white/15"
        >
          Обновить
        </button>
      </div>

      {msg ? <p className="text-sm text-[#ccc] whitespace-pre-wrap">{msg}</p> : null}
    </div>
  )
}
