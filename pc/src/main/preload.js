const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  minimize: () => ipcRenderer.invoke('window-minimize'),
  close: () => ipcRenderer.invoke('window-close'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  getPlatform: () => ipcRenderer.invoke('get-platform'),
  copyToClipboard: (text) => ipcRenderer.invoke('clipboard-write', text),
  vkGuestBootstrap: (authUrl) => ipcRenderer.invoke('vk-guest-bootstrap', authUrl),
  vpnConnect: (config) => ipcRenderer.invoke('vpn-connect', config),
  vpnDisconnect: () => ipcRenderer.invoke('vpn-disconnect'),
  vpnReadConfig: () => ipcRenderer.invoke('vpn-read-config'),
  onVpnLog: (cb) => ipcRenderer.on('vpn-log', (_, line) => cb(line)),
  onVpnReady: (cb) => ipcRenderer.on('vpn-ready', (_, ok) => cb(ok)),
  onVpnError: (cb) => ipcRenderer.on('vpn-error', (_, msg) => cb(msg)),
  onVpnStopped: (cb) => ipcRenderer.on('vpn-stopped', (_, code) => cb(code)),
  removeVpnListeners: () => {
    ipcRenderer.removeAllListeners('vpn-log')
    ipcRenderer.removeAllListeners('vpn-ready')
    ipcRenderer.removeAllListeners('vpn-error')
    ipcRenderer.removeAllListeners('vpn-stopped')
  },
  onVkDeepLink: (cb) => ipcRenderer.on('vk-deep-link', (_, payload) => cb(payload)),
  removeVkDeepLinkListeners: () => ipcRenderer.removeAllListeners('vk-deep-link'),
  listInstalledApps: () => ipcRenderer.invoke('list-installed-apps'),
})
