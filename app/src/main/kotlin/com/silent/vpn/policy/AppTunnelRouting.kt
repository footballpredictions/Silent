package com.silent.vpn.policy

/**
 * Пакеты для VpnService.excludeApplications.
 * ЧС: выбранные + Silent + VK.
 * БС: все установленные кроме выбранных + Silent + VK.
 * includeApplications на OEM часто игнорируется, поэтому БС тоже через exclude.
 */
object AppTunnelRouting {

    data class Policy(
        val whitelist: Boolean,
        val packages: Set<String>,
    )

    fun fromIntent(
        intent: AppExclusionsPersist.TunnelIntent,
        selfPackage: String,
        includeAppInTunnel: Boolean,
        vkPackages: Set<String>,
        installedPackages: Set<String> = emptySet(),
    ): Policy {
        val excluded = LinkedHashSet<String>()
        if (!includeAppInTunnel) {
            excluded.add(selfPackage)
        }
        excluded.addAll(vkPackages)

        if (intent.whitelist) {
            val keep = LinkedHashSet(intent.userPackages)
            keep.removeAll(vkPackages)
            if (includeAppInTunnel) {
                keep.add(selfPackage)
            } else {
                keep.remove(selfPackage)
            }
            for (pkg in installedPackages) {
                if (pkg !in keep) excluded.add(pkg)
            }
            return Policy(
                whitelist = true,
                packages = GoogleAuthTunnelPolicy.excludeWithoutGoogleAuth(excluded),
            )
        }

        excluded.addAll(intent.userPackages)
        return Policy(
            whitelist = false,
            packages = GoogleAuthTunnelPolicy.excludeWithoutGoogleAuth(excluded),
        )
    }
}
