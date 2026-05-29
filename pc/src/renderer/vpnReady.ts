/** Ожидание готовности туннеля — как Android repeat + isInternetReady / tunnelReady. */
export async function waitVpnReady(timeoutMs = 90000): Promise<boolean> {
  const electron = (window as any).electronAPI
  if (!electron?.vpnConnect && !electron?.onVpnReady) return true

  const deadline = Date.now() + timeoutMs
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
    await new Promise(r => setTimeout(r, 1000))
  }
  return listenerOk === true
}
