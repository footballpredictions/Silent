export function normalizeOlcrtcProvider(raw: string): 'telemost' | 'wbstream'
export function shouldAcceptOlcrtcAssign(opts: {
  enabled?: boolean
  cryptoKeyLen?: number
  providerEnabled?: boolean
  room?: string
  denied?: boolean
  poolDenied?: boolean
}): boolean
export function isolateOlcrtcCachePayload<T>(cfg: T, forProvider: string): T | null
