package com.silent.vpn.vpn

data class AppTunnelPolicy(val whitelist: Boolean, val packages: Set<String>)

object AllowedIpsHelper {
    fun generateExclusionAllowedIPs(excludes: Collection<String>): String = error("Past the reinitialization boundary")
}
