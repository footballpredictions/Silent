package com.silent.vpn.policy

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/** Only payment owns this selection; login/mail and the saved main VPN are unchanged. */
internal class PaymentRouteFailover(private val attemptTimeoutMs: Long = 25_000L) {
    private var generation = 0L
    var selected: BootstrapOverlayEndpoint? = null
        private set

    fun clear() {
        generation++
        selected = null
    }

    suspend fun prepare(
        candidates: List<BootstrapOverlayEndpoint>,
        start: suspend (BootstrapOverlayEndpoint, reuse: Boolean) -> Boolean,
        probe: suspend () -> Boolean,
        stop: suspend (BootstrapOverlayEndpoint) -> Unit,
    ): Boolean {
        val ticket = generation
        val routes = (listOfNotNull(selected?.takeIf { it in candidates }) + candidates).distinct()
        var attempted: BootstrapOverlayEndpoint? = null
        for (route in routes) {
            currentCoroutineContext().ensureActive()
            if (ticket != generation) return false
            attempted = route
            val ready = try {
                val result = withTimeoutOrNull(attemptTimeoutMs) {
                    start(route, route == selected) && probe()
                } == true
                currentCoroutineContext().ensureActive()
                result
            } catch (cancelled: CancellationException) {
                if (ticket == generation) withContext(NonCancellable) { stop(route) }
                throw cancelled
            } catch (rejection: PaymentApiRejection) {
                if (ticket == generation) withContext(NonCancellable) { stop(route) }
                throw rejection
            } catch (_: Exception) {
                false
            }
            // A manual connect/disconnect may now own the VPN. Never stop it.
            if (ticket != generation) return false
            if (ready) {
                selected = route
                return true
            }
            selected = null
            // The next attempt retargets the payment transport inside the held VPN.
        }
        if (ticket == generation && attempted != null) withContext(NonCancellable) { stop(attempted) }
        return false
    }

    companion object {
        // Four known exits, bounded startup/HTTPS attempts and service teardown, then init API.
        const val PREPARATION_TIMEOUT_MS = 150_000L

        fun candidates(hiveIp: String, hivePort: Int, cellIps: List<String>): List<BootstrapOverlayEndpoint> {
            val cells = cellIps.filter {
                PaymentTunnelPolicy.isIpv4Host(it) && it != hiveIp && it !in BootstrapOverlayPolicy.AI_EXIT_IPS
            }.distinct().map { BootstrapOverlayEndpoint(it, BootstrapOverlayPolicy.DEFAULT_WDTT_PORT, false) }
            return cells + listOfNotNull(hiveIp.takeIf { PaymentTunnelPolicy.isIpv4Host(it) }
                ?.let { BootstrapOverlayEndpoint(it, hivePort, true) })
        }
    }
}
