declare const __APP_VERSION__: string

interface ElectronUpdateAPI {
  getAppVersion?: () => Promise<string>
  checkForUpdate?: (version: string) => Promise<UpdateInfo | null>
  downloadUpdate?: (url: string, filename: string) => Promise<{ ok: boolean; path?: string; error?: string }>
  installUpdate?: (filePath: string) => Promise<{ ok: boolean; error?: string }>
  onUpdateProgress?: (cb: (pct: number) => void) => void
  removeUpdateListeners?: () => void
}

export {}
