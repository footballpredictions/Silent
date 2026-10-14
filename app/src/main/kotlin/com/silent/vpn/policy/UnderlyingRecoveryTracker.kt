package com.silent.vpn.policy

/** Callback snapshots, independent of racy ConnectivityManager queries during callbacks. */
internal class UnderlyingRecoveryTracker(private val nowMs: () -> Long = { System.nanoTime() / 1_000_000L }) {
    data class NetworkState(
        val id: String,
        val transport: String,
        val internet: Boolean,
        val validated: Boolean,
    )

    private val networks = linkedMapOf<String, NetworkState>()
    private val linkAddresses = mutableMapOf<String, String>()
    private val unvalidatedSinceMs = mutableMapOf<String, Long>()
    private var selectedId: String? = null

    fun selected(): NetworkState? {
        fun rank(state: NetworkState): Int = when {
            !state.internet -> 0
            state.transport == "eth" -> 4
            // Brief validation blips preserve sockets; a sustained WAN loss may hand over to cell.
            state.transport == "wifi" && (state.validated ||
                (state.id == selectedId &&
                    nowMs() - (unvalidatedSinceMs[state.id] ?: nowMs()) < NetworkRecoveryPolicy.VALIDATED_GAP_RECOVER_MS)) -> 3
            state.transport == "cell" -> 2
            state.transport == "wifi" -> 1
            else -> 0
        }
        val maxRank = networks.values.maxOfOrNull(::rank) ?: 0
        if (maxRank == 0) {
            selectedId = null
            return null
        }
        val stable = selectedId?.let(networks::get)?.takeIf { rank(it) == maxRank }
        val selected = stable ?: networks.values.first { rank(it) == maxRank }
        selectedId = selected.id
        return selected
    }

    fun capabilities(state: NetworkState) {
        networks[state.id] = state
        if (state.internet && !state.validated) {
            unvalidatedSinceMs.putIfAbsent(state.id, nowMs())
        } else {
            unvalidatedSinceMs.remove(state.id)
        }
    }

    fun lost(networkId: String): Boolean {
        val wasSelected = selected()?.id == networkId
        networks.remove(networkId)
        linkAddresses.remove(networkId)
        unvalidatedSinceMs.remove(networkId)
        return wasSelected
    }

    /** First observation is a baseline; a new address on the same Network is a handover. */
    fun linkChanged(networkId: String, addressKey: String): Boolean {
        if (addressKey.isEmpty()) return false
        val previous = linkAddresses.put(networkId, addressKey)
        return NetworkRecoveryPolicy.shouldRecoverOnLinkAddrsChange(previous, addressKey)
    }

    fun fingerprint(networkId: String): String = networks[networkId]?.transport.orEmpty()

    fun retainNetworkIds(ids: Set<String>) {
        networks.keys.filter { it !in ids }.forEach { id ->
            networks.remove(id)
            linkAddresses.remove(id)
            unvalidatedSinceMs.remove(id)
        }
    }

    fun clear() {
        networks.clear()
        linkAddresses.clear()
        unvalidatedSinceMs.clear()
        selectedId = null
    }
}
