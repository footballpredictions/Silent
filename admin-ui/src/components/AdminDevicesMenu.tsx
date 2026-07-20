import { useCallback, useEffect, useRef, useState } from 'react'
import { Monitor, Smartphone, Trash2, UserRound, X } from 'lucide-react'

type DeviceRow = {
  id: string
  device_id: string | null
  label: string
  device_type?: string
  ip: string
  last_seen_at: string | null
  created_at: string | null
  is_current: boolean
  is_trusted: boolean
  online?: boolean
}

function fmtDate(iso: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })
  } catch {
    return iso
  }
}

export default function AdminDevicesMenu({
  token,
  onLogout,
}: {
  token: string
  onLogout: () => void
}) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [devices, setDevices] = useState<DeviceRow[]>([])
  const [error, setError] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/admin/sessions', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.status === 401) {
        onLogout()
        return
      }
      if (!res.ok) throw new Error('Не удалось загрузить')
      const data = await res.json()
      setDevices(data.sessions || data.devices || [])
    } catch {
      setError('Ошибка загрузки устройств')
    } finally {
      setLoading(false)
    }
  }, [token, onLogout])

  useEffect(() => {
    if (open) load()
  }, [open, load])

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const revokeDevice = async (row: DeviceRow) => {
    const id = row.device_id || row.id
    try {
      // Prefer device endpoint
      let res = await fetch(`/api/admin/devices/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) {
        res = await fetch(`/api/admin/sessions/${id}`, {
          method: 'DELETE',
          headers: { Authorization: `Bearer ${token}` },
        })
      }
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Ошибка')
      if (row.is_current || data.was_current) {
        localStorage.removeItem('admin_device_token')
        onLogout()
        return
      }
      await load()
    } catch {
      setError('Не удалось удалить устройство')
    }
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="p-1.5 rounded-lg text-[#666] hover:text-white hover:bg-[#1a1a1a] transition-colors"
        title="Устройства админа"
        aria-label="Меню устройств админа"
      >
        <UserRound className="w-4 h-4" />
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-2 z-50 w-[min(100vw-2rem,22rem)] bg-[#111] border border-[#222] rounded-xl shadow-xl overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-[#222]">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Monitor className="w-4 h-4 text-[#888]" />
              Устройства
            </div>
            <button type="button" onClick={() => setOpen(false)} className="text-[#555] hover:text-white p-1">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="max-h-80 overflow-y-auto p-2">
            {loading && <p className="text-xs text-[#666] px-2 py-3 text-center">Загрузка...</p>}
            {error && <p className="text-xs text-red-400 px-2 py-1">{error}</p>}

            {!loading && (
              devices.length === 0 ? (
                <p className="text-xs text-[#555] px-2 py-3 text-center">Нет запомненных устройств</p>
              ) : (
                <ul className="space-y-1">
                  {devices.map(d => {
                    const isPhone = d.device_type === 'phone' || d.device_type === 'tablet'
                    const Icon = isPhone ? Smartphone : Monitor
                    return (
                      <li
                        key={d.device_id || d.id}
                        className="flex items-start gap-2 px-2 py-2 rounded-lg hover:bg-[#1a1a1a] group"
                      >
                        <Icon className="w-4 h-4 text-[#666] mt-0.5 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm text-white truncate">
                            {d.label}
                            {d.is_current && (
                              <span className="ml-1.5 text-[10px] text-[#aaa] font-medium">это устройство</span>
                            )}
                          </p>
                          <p className="text-[11px] text-[#666] truncate">
                            {isPhone ? 'Телефон' : 'ПК'}
                            {d.ip ? ` · ${d.ip}` : ''}
                            {d.online ? ' · онлайн' : ''}
                          </p>
                          <p className="text-[11px] text-[#555]">{fmtDate(d.last_seen_at || d.created_at)}</p>
                        </div>
                        <button
                          type="button"
                          onClick={() => revokeDevice(d)}
                          className="p-1.5 text-[#555] hover:text-white opacity-70 group-hover:opacity-100"
                          title="Удалить устройство"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )
            )}
          </div>
        </div>
      )}
    </div>
  )
}
