const os = require('os')

const NETWORK_POLL_MS = 3000
const NETWORK_GRACE_MS = 90_000
const NETWORK_GRACE_AFTER_READY_MS = 90_000
const TRANSPORT_DEBOUNCE_MS = 15_000

/** Как Android NET_CAPABILITY_NOT_VPN — wg-turn не считается «интернетом». */
function isVpnInterface(name) {
  const n = (name || '').toLowerCase()
  return (
    n.includes('wg-turn')
    || n.includes('wireguard')
    || n.includes('wintun')
    || n.includes('tailscale')
    || n === 'wg0'
    || /^wg\d*$/.test(n)
  )
}

function isPhysicalInterface(name) {
  const n = (name || '').toLowerCase()
  if (isVpnInterface(name)) return false
  if (n.includes('vethernet') || n.includes('wsl') || n.includes('hyper-v') || n.includes('loopback')) {
    return false
  }
  return true
}

function hasUnderlyingInternet() {
  const nets = os.networkInterfaces()
  for (const [name, addrs] of Object.entries(nets)) {
    if (!isPhysicalInterface(name)) continue
    if (!addrs) continue
    for (const a of addrs) {
      if (a.internal) continue
      if (a.family === 'IPv4' || a.family === 4) return true
    }
  }
  return false
}

function detectTransportKey() {
  const nets = os.networkInterfaces()
  for (const [name, addrs] of Object.entries(nets)) {
    if (!isPhysicalInterface(name)) continue
    if (!addrs?.some(a => !a.internal && (a.family === 'IPv4' || a.family === 4))) continue
    const n = name.toLowerCase()
    if (n.includes('wi-fi') || n.includes('wifi') || n.includes('wlan')) return 'wifi'
    if (n.includes('ethernet') || n.includes('eth')) return 'ethernet'
    return name
  }
  return null
}

/**
 * Как Android: pause при обрыве сети; restartTransport только если libclient реально мёртв.
 */
function createNetworkMonitor(state, actions) {
  let timer = null
  let lastOnline = hasUnderlyingInternet()
  let lastTransport = detectTransportKey()
  let lastTransportChangeMs = 0

  function tick() {
    if (!state.vpnSessionActive) return

    const online = hasUnderlyingInternet()
    const transport = detectTransportKey()
    const elapsed = Date.now() - state.connectStartedAtMs
    const grace = state.wgApplied ? NETWORK_GRACE_AFTER_READY_MS : NETWORK_GRACE_MS

    if (actions.isTransportHealthy()) {
      lastOnline = online
      if (online && transport) lastTransport = transport
      return
    }

    if (lastOnline && !online) {
      if (elapsed >= grace && state.wgApplied && !state.pausedForNetwork) {
        actions.pauseWdtt('потеря сети')
      }
    } else if (!lastOnline && online) {
      actions.restoreTransport('сеть восстановлена')
    }
    lastOnline = online

    if (
      online
      && state.wgApplied
      && transport
      && lastTransport
      && transport !== lastTransport
      && elapsed >= grace
    ) {
      const now = Date.now()
      if (now - lastTransportChangeMs >= TRANSPORT_DEBOUNCE_MS) {
        lastTransportChangeMs = now
        actions.restoreTransport(`смена транспорта ${lastTransport} → ${transport}`)
      }
    }
    if (online && transport) lastTransport = transport

    if (online && state.wgApplied && elapsed >= NETWORK_GRACE_AFTER_READY_MS) {
      const sinceWdtt = state.wdttStartedAtMs > 0 ? Date.now() - state.wdttStartedAtMs : 0
      if (sinceWdtt > 0 && sinceWdtt < NETWORK_GRACE_AFTER_READY_MS) return
      if (!actions.isTransportHealthy()) {
        actions.restoreTransport('watchdog')
      }
    }
  }

  return {
    start() {
      this.stop()
      lastOnline = hasUnderlyingInternet()
      lastTransport = detectTransportKey()
      timer = setInterval(tick, NETWORK_POLL_MS)
    },
    stop() {
      if (timer) {
        clearInterval(timer)
        timer = null
      }
    },
  }
}

module.exports = {
  createNetworkMonitor,
  hasUnderlyingInternet,
  isVpnInterface,
  NETWORK_GRACE_MS,
  NETWORK_GRACE_AFTER_READY_MS,
}
