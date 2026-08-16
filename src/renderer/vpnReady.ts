import { connectWaitTimeoutForAuth } from './hashChannelHelper'

export type VpnReadyWaitResult = true | false | 'flood'

/** Как Android waitForTunnelReady: flood/0 воркеров → каскад капчи, не «туннель не поднялся». */
const FLOOD_ESCALATE_AFTER_MS = 3_000

/** Ожидание готовности туннеля — как Android waitForTunnelReady. */
export async function waitVpnReady(
  timeoutMs?: number,
  totalWorkers = 63,
  isBootstrap = false,
  vkAuthMode?: string,
): Promise<VpnReadyWaitResult> {
  const deadlineMs =
    timeoutMs ?? connectWaitTimeoutForAuth(totalWorkers, isBootstrap, vkAuthMode)
  const electron = (window as any).electronAPI
  if (!electron?.vpnConnect && !electron?.onVpnReady) return true

  const deadline = Date.now() + deadlineMs
  const started = Date.now()
  let listenerOk: boolean | null = null
  const legacy = String(vkAuthMode || '').toLowerCase() === 'legacy'

  if (electron.onVpnReady) {
    electron.onVpnReady((payload: boolean | { ok?: boolean; bootstrap?: boolean }) => {
      const ok = typeof payload === 'object' ? !!payload?.ok : !!payload
      const bootstrap = typeof payload === 'object' ? !!payload?.bootstrap : false
      if (!ok) return
      if (isBootstrap ? bootstrap : !bootstrap) listenerOk = true
    })
  }

  while (Date.now() < deadline) {
    if (listenerOk) return true
    try {
      if (electron.vpnIsReady) {
        const r = await electron.vpnIsReady()
        if (isBootstrap ? r?.bootstrap : r?.ready && !r?.bootstrap) return true
        if (!isBootstrap && (r?.workers > 0) && r?.wg) return true
        // Android: tick>=30 (3с), 0 воркеров, flood/LEGACY_ESCALATE → капча.
        // WG из кеша / installing не блокируют: звонок уже мёртв.
        if (
          !legacy &&
          Date.now() - started >= FLOOD_ESCALATE_AFTER_MS &&
          !(r?.workers > 0) &&
          electron.consumeFloodEscalate
        ) {
          const flood = await electron.consumeFloodEscalate()
          if (flood?.escalate) return 'flood'
        }
      }
    } catch {
      /* ignore */
    }
    await new Promise(r => setTimeout(r, 200))
  }
  if (listenerOk) return true
  try {
    const r = await electron.vpnIsReady?.()
    if (isBootstrap ? r?.bootstrap : r?.ready && !r?.bootstrap) return true
    if (!isBootstrap && (r?.workers > 0) && r?.wg) return true
    // Таймаут без воркеров = как Android: vkcalls/auto → следующий режим, не alert WG.
    if (!(r?.workers > 0)) return 'flood'
  } catch {
    /* ignore */
  }
  return false
}
