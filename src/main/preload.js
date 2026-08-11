const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  minimize: () => ipcRenderer.invoke('window-minimize'),
  close: () => ipcRenderer.invoke('window-close'),
  quitApp: () => ipcRenderer.invoke('app-quit'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  getAdminPanelUrl: () => ipcRenderer.invoke('get-admin-panel-url'),
  openAdminPanel: () => ipcRenderer.invoke('open-admin-panel'),
  getPlatform: () => ipcRenderer.invoke('get-platform'),
  copyToClipboard: (text) => ipcRenderer.invoke('clipboard-write', text),
  vkGuestBootstrap: (authUrl) => ipcRenderer.invoke('vk-guest-bootstrap', authUrl),
  vpnConnect: (config) => ipcRenderer.invoke('vpn-connect', config),
  vpnDisconnect: (opts) => ipcRenderer.invoke('vpn-disconnect', opts),
  vpnIsReady: () => ipcRenderer.invoke('vpn-is-ready'),
  vpnReadConfig: () => ipcRenderer.invoke('vpn-read-config'),
  consumeFloodEscalate: () => ipcRenderer.invoke('vpn-consume-flood-escalate'),
  onVpnLog: (cb) => ipcRenderer.on('vpn-log', (_, line) => cb(line)),
  onWdttLog: (cb) => ipcRenderer.on('wdtt-log', (_, entry) => cb(entry)),
  onWdttLogBatch: (cb) => ipcRenderer.on('wdtt-log-batch', (_, batch) => cb(batch)),
  onDebugLog: (cb) => ipcRenderer.on('debug-log', (_, payload) => cb(payload)),
  onVpnReady: (cb) => ipcRenderer.on('vpn-ready', (_, payload) => cb(payload)),
  onVpnError: (cb) => ipcRenderer.on('vpn-error', (_, msg) => cb(msg)),
  onVpnStopped: (cb) => ipcRenderer.on('vpn-stopped', (_, code) => cb(code)),
  onOlcrtcRoomDead: (cb) => ipcRenderer.on('olcrtc-room-dead', (_, payload) => cb(payload)),
  onHashFailure: (cb) => ipcRenderer.on('hash-failure', (_, payload) => cb(payload)),
  removeVpnListeners: () => {
    ipcRenderer.removeAllListeners('vpn-log')
    ipcRenderer.removeAllListeners('wdtt-log')
    ipcRenderer.removeAllListeners('wdtt-log-batch')
    ipcRenderer.removeAllListeners('vpn-ready')
    ipcRenderer.removeAllListeners('vpn-error')
    ipcRenderer.removeAllListeners('vpn-stopped')
    ipcRenderer.removeAllListeners('olcrtc-room-dead')
    ipcRenderer.removeAllListeners('hash-failure')
  },
  removeDebugLogListeners: () => {
    ipcRenderer.removeAllListeners('debug-log')
  },
  onVkDeepLink: (cb) => ipcRenderer.on('vk-deep-link', (_, payload) => cb(payload)),
  removeVkDeepLinkListeners: () => ipcRenderer.removeAllListeners('vk-deep-link'),
  onRefDeepLink: (cb) => ipcRenderer.on('ref-deep-link', (_, payload) => cb(payload)),
  removeRefDeepLinkListeners: () => ipcRenderer.removeAllListeners('ref-deep-link'),
  listInstalledApps: () => ipcRenderer.invoke('list-installed-apps'),
  saveAppExclusions: (payload) => ipcRenderer.invoke('save-app-exclusions', payload),
  getAppExclusions: () => ipcRenderer.invoke('get-app-exclusions'),
  saveSiteBypass: (payload) => ipcRenderer.invoke('save-site-bypass', payload),
  getSiteBypass: () => ipcRenderer.invoke('get-site-bypass'),
  warmupTelegramPath: () => ipcRenderer.invoke('warmup-telegram-path'),
  getAppVersion: () => ipcRenderer.invoke('app-version'),
  checkForUpdate: (version) => ipcRenderer.invoke('app-update-check', { version, platform: 'pc' }),
  tunnelApiRequest: (payload) => ipcRenderer.invoke('tunnel-api-request', payload),
  downloadUpdate: (url, filename) => ipcRenderer.invoke('app-update-download', { url, filename }),
  downloadUpdateMeta: (payload) => ipcRenderer.invoke('app-update-download', payload),
  installUpdate: (filePath) => ipcRenderer.invoke('app-update-install', filePath),
  onUpdateProgress: (cb) => ipcRenderer.on('update-progress', (_, pct) => cb(pct)),
  removeUpdateListeners: () => ipcRenderer.removeAllListeners('update-progress'),
})
