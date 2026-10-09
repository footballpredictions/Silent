package com.silent.vpn.policy

import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive

/** The caller keeps the payment API route alive until a fresh paid profile is applied. */
internal suspend fun <P> refreshPaidPaymentProfile(
    fetch: suspend () -> P,
    isPaid: (P) -> Boolean,
    apply: (P) -> Unit,
): Boolean {
    val profile = fetch()
    currentCoroutineContext().ensureActive()
    if (!isPaid(profile)) return false
    apply(profile)
    return true
}
