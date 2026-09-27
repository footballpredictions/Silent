/** Debug-сборка: npm run dev или packaged build с DEBUG_BUILD=1. Release installer — всегда false. */
declare const __DEBUG_BUILD__: boolean | undefined

export const isDebugBuild =
  import.meta.env.DEV || (typeof __DEBUG_BUILD__ !== 'undefined' && __DEBUG_BUILD__)

function clientPlatform(): string {
  if (typeof window === 'undefined') return ''
  const api = (window as Window & { electronAPI?: { platform?: string } }).electronAPI
  return String(api?.platform || '')
}

/** Релиз Mac: кнопка «Лог» и строки WDTT/[WG], иначе панель пустая. */
export const isMacClient = clientPlatform() === 'mac'
export const captureBuiltinLog = isDebugBuild || isMacClient
