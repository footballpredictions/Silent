import { connectWaitTimeoutForAuth } from './hashChannelHelper'

export type VpnReadyWaitResult = true | false | 'flood'

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
        // Flood control: vkcalls→автокапча. Не рвать, если WG уже ставится.
        if (
          !legacy &&
          Date.now() - started > 15_000 &&
          !(r?.workers > 0) &&
          !r?.wg &&
          !r?.installing &&
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
  return listenerOk === true
}
