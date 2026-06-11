import { useEffect } from 'react'
import { ingestWdttLog, pushAppLog } from './vpnLogStore'

/** Подписка на wdtt-log + debug-log из main (как Android WdttTunnelManager → DebugLogDialog). */
export function useVpnLogSubscription(enabled = true) {
  useEffect(() => {
    if (!enabled) return
    const api_ = (window as any).electronAPI
    if (!api_) return

    const onWdtt = (entry: {
      key?: string
      message?: string
      priority?: number
      isError?: boolean
    }) => {
      ingestWdttLog(entry)
    }

    const onDebug = (payload: { tag?: string; level?: string; message?: string }) => {
      const tag = payload.tag || 'Main'
      const msg = payload.message || ''
      const lvl = (payload.level || 'I').toUpperCase()
      const level = lvl === 'E' ? 'E' : lvl === 'W' ? 'W' : 'I'
      pushAppLog(tag, msg, level)
    }

    api_.onWdttLog?.(onWdtt)
    api_.onDebugLog?.(onDebug)
    return () => {
      api_.removeDebugLogListeners?.()
      api_.removeVpnListeners?.()
    }
  }, [enabled])
}
