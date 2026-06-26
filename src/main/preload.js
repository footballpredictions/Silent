const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  minimize: () => ipcRenderer.invoke('window-minimize'),
  close: () => ipcRenderer.invoke('window-close'),
  quitApp: () => ipcRenderer.invoke('app-quit'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  getPlatform: () => ipcRenderer.invoke('get-platform'),
  copyToClipboard: (text) => ipcRenderer.invoke('clipboard-write', text),
  vkGuestBootstrap: (authUrl) => ipcRenderer.invoke('vk-guest-bootstrap', authUrl),
  vpnConnect: (config) => ipcRenderer.invoke('vpn-connect', config),
  vpnDisconnect: (opts) => ipcRenderer.invoke('vpn-disconnect', opts),
  vpnIsReady: () => ipcRenderer.invoke('vpn-is-ready'),
  vpnReadConfig: () => ipcRenderer.invoke('vpn-read-config'),
  onVpnLog: (cb) => ipcRenderer.on('vpn-log', (_, line) => cb(line)),
  onWdttLog: (cb) => ipcRenderer.on('wdtt-log', (_, entry) => cb(entry)),
  onDebugLog: (cb) => ipcRenderer.on('debug-log', (_, payload) => cb(payload)),
  onVpnReady: (cb) => ipcRenderer.on('vpn-ready', (_, payload) => cb(payload)),
  onVpnError: (cb) => ipcRenderer.on('vpn-error', (_, msg) => cb(msg)),
  onVpnStopped: (cb) => ipcRenderer.on('vpn-stopped', (_, code) => cb(code)),
  onHashFailure: (cb) => ipcRenderer.on('hash-failure', (_, payload) => cb(payload)),
  removeVpnListeners: () => {
    ipcRenderer.removeAllListeners('vpn-log')
    ipcRenderer.removeAllListeners('wdtt-log')
    ipcRenderer.removeAllListeners('vpn-ready')
    ipcRenderer.removeAllListeners('vpn-error')
    ipcRenderer.removeAllListeners('vpn-stopped')
    ipcRenderer.removeAllListeners('hash-failure')
  },
  removeDebugLogListeners: () => {
    ipcRenderer.removeAllListeners('debug-log')
  },
  onVkDeepLink: (cb) => ipcRenderer.on('vk-deep-link', (_, payload) => cb(payload)),
  removeVkDeepLinkListeners: () => ipcRenderer.removeAllListeners('vk-deep-link'),
  listInstalledApps: () => ipcRenderer.invoke('list-installed-apps'),
  getAppVersion: () => ipcRenderer.invoke('app-version'),
  checkForUpdate: (version) => ipcRenderer.invoke('app-update-check', { version, platform: 'pc' }),
  downloadUpdate: (url, filename) => ipcRenderer.invoke('app-update-download', { url, filename }),
  installUpdate: (filePath) => ipcRenderer.invoke('app-update-install', filePath),
  onUpdateProgress: (cb) => ipcRenderer.on('update-progress', (_, pct) => cb(pct)),
  removeUpdateListeners: () => ipcRenderer.removeAllListeners('update-progress'),
})
