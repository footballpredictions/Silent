import { connectWaitTimeoutForAuth } from './hashChannelHelper'

/** Ожидание готовности туннеля — как Android waitForTunnelReady. */
export async function waitVpnReady(
  timeoutMs?: number,
  totalWorkers = 63,
  isBootstrap = false,
  vkAuthMode?: string,
): Promise<boolean> {
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
        // LEGACY_ESCALATE при 0 воркерах — не ждать полный timeout с n=63
        if (
          !legacy &&
          Date.now() - started > 8_000 &&
          !(r?.workers > 0) &&
          electron.consumeFloodEscalate
        ) {
          const flood = await electron.consumeFloodEscalate()
          if (flood?.escalate) return false
        }
      }
    } catch {
      /* ignore */
    }
    await new Promise(r => setTimeout(r, 200))
  }
  return listenerOk === true
}
