import { useEffect } from 'react'
import { ingestMainLog, logD, logE, logI, logW } from './debugLog'

/** Подписка на vpn-log + debug-log из main process (как Android WdttTunnelManager → DebugLog). */
export function useVpnLogSubscription(enabled = true) {
  useEffect(() => {
    if (!enabled) return
    const api_ = (window as any).electronAPI
    if (!api_) return

    const onDebug = (payload: { tag?: string; level?: string; message?: string }) => {
      ingestMainLog(payload)
    }

    const onLog = (line: string) => {
      if (!line?.trim()) return
      const trimmed = line.trim()
      if (/Активных:\s*\d+/.test(trimmed)) {
        logD('VPN', trimmed)
        return
      }
      if (/^\[WG\]/.test(trimmed)) {
        if (/error|ошиб|fail|таймаут/i.test(trimmed)) logE('WireGuard', trimmed)
        else logI('WireGuard', trimmed)
        return
      }
      if (/error|ошиб|fail|таймаут/i.test(trimmed)) logE('VPN', trimmed)
      else if (/WARN|⚠/i.test(trimmed)) logW('VPN', trimmed)
      else logI('VPN', trimmed)
    }

    api_.onDebugLog?.(onDebug)
    api_.onVpnLog?.(onLog)
    return () => {
      api_.removeDebugLogListeners?.()
      api_.removeVpnListeners?.()
    }
  }, [enabled])
}
