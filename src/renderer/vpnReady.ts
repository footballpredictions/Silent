import { connectWaitTimeoutMs } from './hashChannelHelper'

/** Ожидание готовности туннеля — как Android waitForTunnelReady. */
export async function waitVpnReady(
  timeoutMs?: number,
  totalWorkers = 63,
  isBootstrap = false,
): Promise<boolean> {
  const deadlineMs = timeoutMs ?? connectWaitTimeoutMs(totalWorkers, isBootstrap)
  const electron = (window as any).electronAPI
  if (!electron?.vpnConnect && !electron?.onVpnReady) return true

  const deadline = Date.now() + deadlineMs
  let listenerOk: boolean | null = null

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
      }
    } catch {
      /* ignore */
    }
    await new Promise(r => setTimeout(r, 200))
  }
  return listenerOk === true
}
