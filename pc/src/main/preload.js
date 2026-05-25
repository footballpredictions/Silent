const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  minimize: () => ipcRenderer.invoke('window-minimize'),
  close: () => ipcRenderer.invoke('window-close'),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  getPlatform: () => ipcRenderer.invoke('get-platform'),
  vpnConnect: (config) => ipcRenderer.invoke('vpn-connect', config),
  vpnDisconnect: () => ipcRenderer.invoke('vpn-disconnect'),
  vpnReadConfig: () => ipcRenderer.invoke('vpn-read-config'),
  onVpnLog: (cb) => ipcRenderer.on('vpn-log', (_, line) => cb(line)),
  onVpnStopped: (cb) => ipcRenderer.on('vpn-stopped', (_, code) => cb(code)),
  removeVpnListeners: () => {
    ipcRenderer.removeAllListeners('vpn-log')
    ipcRenderer.removeAllListeners('vpn-stopped')
  },
})
