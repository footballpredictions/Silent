/** Debug-сборка: npm run dev или packaged build с DEBUG_BUILD=1. Release installer — всегда false. */
declare const __DEBUG_BUILD__: boolean | undefined

export const isDebugBuild =
  import.meta.env.DEV || (typeof __DEBUG_BUILD__ !== 'undefined' && __DEBUG_BUILD__)
