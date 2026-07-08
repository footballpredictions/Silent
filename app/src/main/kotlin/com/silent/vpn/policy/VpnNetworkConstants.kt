package com.silent.vpn.policy

object VpnNetworkConstants {
    const val DEFAULT_SERVER_HOST = "132-243-234-162.nip.io"
    const val WG_TUNNEL_GATEWAY = "10.66.66.1"
    const val TUNNEL_API_BASE = "http://$WG_TUNNEL_GATEWAY:8000"
    const val POST_TUNNEL_SYNC_QUIET_MS = 90_000L
    const val MIN_TRANSPORT_RESTART_INTERVAL_MS = 90_000L
}
