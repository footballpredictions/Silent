import { connectWaitTimeoutMs } from './hashChannelHelper'

/** Ожидание готовности туннеля — как Android waitForTunnelReady. */
export async function waitVpnReady(
  timeoutMs?: number,
  totalWorkers = 108,
  isBootstrap = false,
): Promise<boolean> {
  const deadlineMs = timeoutMs ?? connectWaitTimeoutMs(totalWorkers, isBootstrap)
  const electron = (window as any).electronAPI
  if (!electron?.vpnConnect && !electron?.onVpnReady) return true

  const deadline = Date.now() + deadlineMs
  let listenerOk: boolean | null = null

  if (electron.onVpnReady) {
    electron.onVpnReady((ok: boolean) => {
      if (ok) listenerOk = true
    })
  }

  while (Date.now() < deadline) {
    if (listenerOk) return true
    try {
      if (electron.vpnIsReady) {
        const r = await electron.vpnIsReady()
        if (r?.ready) return true
      }
    } catch {
      /* ignore */
    }
    await new Promise(r => setTimeout(r, 200))
  }
  return listenerOk === true
}
