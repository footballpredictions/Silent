import { useEffect, useState } from 'react'
import api from '../api'
import { getStableDeviceFingerprint } from '../api'
import { isDebugBuild } from '../debugBuild'
import {
  getPreferredServer,
  setPreferredServer,
  normalizePreferredServer,
  rememberVpnServerIps,
} from '../bypassStore'

type Props = {
  fg: string
  muted: string
  bg: string
  surface?: string
  primary: string
  vpnRunning: boolean
  onBack: () => void
}

function ModeOption({
  title,
  selected,
  enabled,
  fg,
  muted,
  onSelect,
}: {
  title: string
  selected: boolean
  enabled: boolean
  fg: string
  muted: string
  onSelect: () => void
}) {
  return (
    <label
      className="flex items-center cursor-pointer"
      style={{ opacity: enabled ? 1 : 0.45, padding: '8px 0' }}
    >
      <span
        className="shrink-0 rounded-full flex items-center justify-center"
        style={{
          width: 20,
          height: 20,
          border: `2px solid ${selected ? fg : muted}`,
          boxSizing: 'border-box',
        }}
        aria-hidden
      >
        {selected ? (
          <span className="rounded-full" style={{ width: 10, height: 10, background: fg }} />
        ) : null}
      </span>
      <input
        type="radio"
        checked={selected}
        disabled={!enabled}
        onChange={() => enabled && onSelect()}
        className="sr-only"
      />
      <div className="text-sm font-medium" style={{ color: fg, marginLeft: 8 }}>{title}</div>
    </label>
  )
}

type VpnServerInfo = {
  key: string
  title: string
  public_ip: string
  wdtt_port: number
  online_count: number
  api_base?: string
}

type VpnServersResponse = {
  selected_server?: string | null
  servers: VpnServerInfo[]
}

function slotTitle(slot: string): string {
  const n = String(slot || '').replace(/^server/i, '')
  return n && /^\d+$/.test(n) ? `Сервер ${n}` : slot
}

const AI_SERVER_SLOT = 'server4'
const AI_SERVER_TITLE = 'Сервер 4 для ИИ'

/**
 * Тестовая сборка: слот ИИ-соты в списке всегда, даже пока список серверов не
 * пришёл с API. Права не проверяем — сота помечена admin_only, и не-админу
 * сервер сам ответит 403 на выборе. В release список целиком с сервера.
 */
function withDebugAiServer(list: VpnServerInfo[]): VpnServerInfo[] {
  if (!isDebugBuild) return list
  const ai: VpnServerInfo = {
    key: AI_SERVER_SLOT,
    title: AI_SERVER_TITLE,
    public_ip: '',
    wdtt_port: 0,
    online_count: 0,
  }
  const idx = list.findIndex((s) => normalizePreferredServer(s.key) === AI_SERVER_SLOT)
  if (idx < 0) return [...list, ai]
  const known = list[idx]
  // Подпись с сервера главнее; заменяем только локальную заглушку «Сервер 4».
  if (known.title && known.title !== slotTitle(AI_SERVER_SLOT)) return list
  const next = [...list]
  next[idx] = { ...known, title: AI_SERVER_TITLE }
  return next
}

function applyDialogLine(fromSlot: string, toSlot: string, servers: VpnServerInfo[]): string {
  const titleOf = (key: string) =>
    servers.find((s) => normalizePreferredServer(s.key) === key)?.title || slotTitle(key)
  if (fromSlot !== toSlot) {
    return `${titleOf(fromSlot)} → ${titleOf(toSlot)}`
  }
  return titleOf(toSlot)
}

/**
 * Как 1.0.160 / Android: радио ставят pending, подтверждение — диалог «Применить?».
 */
export default function MenuBypassPanel({
  fg,
  muted,
  bg,
  surface,
  primary,
  vpnRunning,
  onBack,
}: Props) {
  const [selectedServerSlot, setSelectedServerSlot] = useState(
    normalizePreferredServer(getPreferredServer()),
  )
  const [servers, setServers] = useState<VpnServerInfo[]>([])
  const [pendingServerSlot, setPendingServerSlot] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const switchLocked = busy || vpnRunning

  const selServer = pendingServerSlot ?? selectedServerSlot
  const hasPending =
    (pendingServerSlot != null && pendingServerSlot !== selectedServerSlot)

  const clearPending = () => {
    setPendingServerSlot(null)
  }

  useEffect(() => {
    let mounted = true
    ;(async () => {
      try {
        const fp = getStableDeviceFingerprint()
        const res = await api.get('/api/vpn/servers', { params: { fingerprint: fp } })
        const data = res.data as VpnServersResponse
        if (!mounted) return
        const list = Array.isArray(data.servers) ? data.servers : []
        setServers(withDebugAiServer(list))
        rememberVpnServerIps(list)
        // Локальный слот — источник правды. GET selected_server часто отстаёт
        // (устройство ещё на соте) и откатывал «Сервер 1» обратно на 2/3.
        const local = normalizePreferredServer(getPreferredServer())
        setSelectedServerSlot(local)
      } catch {
        if (mounted) setHint('Не удалось загрузить список серверов.')
      }
    })()
    return () => { mounted = false }
  }, [])

  useEffect(() => {
    if (!switchLocked) {
      if (hint === 'Отключите VPN перед сменой сервера.') setHint(null)
      return
    }
    clearPending()
    setHint('Отключите VPN перед сменой сервера.')
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [switchLocked])

  const applyPending = async () => {
    if (busy || !hasPending) return
    const nextServer = pendingServerSlot ?? selectedServerSlot
    const willChange =
      nextServer !== selectedServerSlot
    clearPending()
    setBusy(true)
    setHint(null)
    try {
      if (willChange && switchLocked) {
        setHint('Сначала отключите VPN, затем меняйте сервер.')
        return
      }
      if (nextServer !== selectedServerSlot) {
        const prevServer = selectedServerSlot
        setSelectedServerSlot(nextServer)
        setPreferredServer(nextServer)
        try {
          const fp = getStableDeviceFingerprint()
          const res = await api.post('/api/vpn/servers/select', {
            device_fingerprint: fp,
            preferred_server: nextServer,
          })
          const data = res.data as VpnServersResponse
          const nextServers = Array.isArray(data.servers) ? data.servers : []
          if (nextServers.length > 0) setServers(withDebugAiServer(nextServers))
          rememberVpnServerIps(nextServers)
          setHint('Выбрано')
        } catch (e: any) {
          if (e?.response?.status === 403) {
            // Иначе остались бы с пином, которого на сервере нет: конфиг придёт
            // от Улья и не сойдётся с ожидаемым IP слота.
            setPreferredServer(prevServer)
            setSelectedServerSlot(prevServer)
            setHint('Сервер доступен только администратору.')
          } else {
            setHint('Выбрано. Синхронизация с сервером при подключении.')
          }
        }
      } else {
        setHint('Выбрано')
      }
    } finally {
      setBusy(false)
    }
  }

  const btnBg = primary || fg
  const btnFg = bg

  return (
    <div className="relative flex flex-col h-full p-4 min-h-0">
      <button type="button" onClick={onBack} className="text-xs self-start mb-4 hover:opacity-70" style={{ color: muted }}>
        ← Назад
      </button>
      <h2 className="text-sm font-semibold mb-3" style={{ color: fg }}>Выбор сервера</h2>
      {hint ? (
        <p className="text-[11px] mb-2" style={{ color: muted }}>{hint}</p>
      ) : null}
      {switchLocked ? (
        <p className="text-[11px] mb-2" style={{ color: muted }}>
          Переключение недоступно: VPN активен.
        </p>
      ) : null}

      <div className="flex-1 overflow-y-auto min-h-0">
        <div style={{ paddingLeft: 12 }}>
          {(servers.length > 0 ? servers : withDebugAiServer([
            { key: 'server1', title: 'Сервер 1', public_ip: '', wdtt_port: 0, online_count: 0 },
            { key: 'server2', title: 'Сервер 2', public_ip: '', wdtt_port: 0, online_count: 0 },
            { key: 'server3', title: 'Сервер 3', public_ip: '', wdtt_port: 0, online_count: 0 },
          ])).map((server) => {
            const slot = normalizePreferredServer(server.key)
            return (
            <div key={slot}>
              <ModeOption
                title={server.title || slotTitle(slot)}
                selected={selServer === slot}
                enabled={!switchLocked}
                fg={fg}
                muted={muted}
                onSelect={() => {
                  setPendingServerSlot(slot)
                }}
              />
            </div>
          )})}
        </div>
      </div>

      {(hasPending && !switchLocked) && (
        <div
          className="absolute inset-0 z-20 flex items-center justify-center px-6"
          style={{ background: 'rgba(0,0,0,0.46)' }}
          onClick={() => {
            if (!busy) clearPending()
          }}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="bypass-apply-title"
            className="w-full max-w-[280px] px-6 pt-5 pb-4"
            style={{
              background: surface || bg,
              color: fg,
              borderRadius: 28,
              boxShadow: '0 8px 28px rgba(0,0,0,0.45)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div id="bypass-apply-title" className="text-[22px] font-normal leading-7 mb-3">
              Применить?
            </div>
            <p className="text-sm leading-5 mb-6" style={{ color: muted }}>
              {applyDialogLine(selectedServerSlot, selServer, servers)}
            </p>
            <div className="flex justify-end items-center gap-2">
                <button
                  type="button"
                  className="px-3 py-2 text-sm"
                  style={{ color: `${fg}99` }}
                  onClick={clearPending}
                >
                  Отмена
                </button>
                <button
                  type="button"
                  className="px-4 py-1.5 text-sm font-medium"
                  style={{ background: btnBg, color: btnFg, borderRadius: 20 }}
                  onClick={() => void applyPending()}
                >
                  Применить
                </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
