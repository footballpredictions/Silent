package com.silent.vpn.sync

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Статус фоновой синхронизации для UI (без отдельного процесса — общий VPN Network). */
object VpnDataSyncState {
    enum class Phase { IDLE, SYNCING, OK, ERROR }

    data class Status(
        val phase: Phase = Phase.IDLE,
        val message: String? = null,
        val lastSuccessAtMs: Long = 0L,
    )

    private val _status = MutableStateFlow(Status())
    val status: StateFlow<Status> = _status.asStateFlow()

    fun setSyncing(message: String = "Синхронизация данных…") {
        _status.value = _status.value.copy(phase = Phase.SYNCING, message = message)
    }

    fun setOk(message: String? = null) {
        _status.value = Status(phase = Phase.OK, message = message, lastSuccessAtMs = System.currentTimeMillis())
    }

    fun setError(message: String) {
        _status.value = _status.value.copy(phase = Phase.ERROR, message = message)
    }

    fun setIdle() {
        _status.value = Status()
    }
}
