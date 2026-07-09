import { useEffect } from 'react'
import { ingestWdttLog, ingestWdttLogBatch, pushAppLog } from './vpnLogStore'
import { reportHashFailure } from './hashFailureReporter'

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
      _hits?: number
    }) => {
      ingestWdttLog(entry)
    }

    const onWdttBatch = (
      batch: Array<{
        key?: string
        message?: string
        priority?: number
        isError?: boolean
        _hits?: number
      }>,
    ) => {
      ingestWdttLogBatch(batch)
    }

    const onDebug = (payload: { tag?: string; level?: string; message?: string }) => {
      const tag = payload.tag || 'Main'
      const msg = payload.message || ''
      const lvl = (payload.level || 'I').toUpperCase()
      const level = lvl === 'E' ? 'E' : lvl === 'W' ? 'W' : 'I'
      pushAppLog(tag, msg, level)
    }

    const onHashFailure = (payload: { hash?: string; errorType?: string; message?: string }) => {
      if (!payload?.hash) return
      void reportHashFailure(
        payload.hash,
        payload.errorType || 'unknown',
        payload.message || '',
      )
    }

    const onVpnError = (msg: string) => {
      const text = String(msg || '').trim()
      if (!text) return
      pushAppLog('VPN', text, 'E')
    }

    api_.onWdttLog?.(onWdtt)
    api_.onWdttLogBatch?.(onWdttBatch)
    api_.onDebugLog?.(onDebug)
    api_.onVpnError?.(onVpnError)
    api_.onHashFailure?.(onHashFailure)
    return () => {
      api_.removeDebugLogListeners?.()
      api_.removeVpnListeners?.()
    }
  }, [enabled])
}
