package com.silent.vpn.policy

/**
 * Временный интернет на экране входа.
 * [VpnService.Builder.addAllowedApplication] (includeApplications) на OEM
 * (vivo/Xiaomi/Huawei) часто no-op: в туннеле остаётся только Silent VPN,
 * почтовый клиент сидит на заблокированном LTE.
 * Поэтому bootstrap — полный туннель через excludeApplications: наружу только VK.
 */
object BootstrapTunnelAppsPolicy {

    fun excludeFromTunnel(
        vkPackages: Set<String>,
        installedPackages: Set<String>,
        selfPackage: String,
    ): Set<String> =
        vkPackages.filter { it != selfPackage && it in installedPackages }.toSet()
}
