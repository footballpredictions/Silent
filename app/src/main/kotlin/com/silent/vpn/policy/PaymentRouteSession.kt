package com.silent.vpn.policy

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive

internal data class PreparedPaymentRoute<A, P, K>(val api: A, val preview: P, val identity: K)
internal class PaymentApiRejection(message: String) : IllegalStateException(message)

/** One preparation for preview -> confirmation -> browser. Only reads may fail over. */
internal class PaymentRouteSession<A, P : Any, K>(clock: () -> Long) {
    private val reservation = PaymentRouteReservation<K, PreparedPaymentRoute<A, P, K>>(clock)
    fun clear() = reservation.clear()

    suspend fun prepare(
        identity: () -> K,
        stillOwned: () -> Boolean,
        currentBases: List<String>,
        siteAvailable: suspend () -> Boolean,
        api: (String) -> A,
        preview: suspend (A) -> P?,
        temporary: suspend () -> Pair<A, P>,
    ): PreparedPaymentRoute<A, P, K> {
        currentCoroutineContext().ensureActive()
        check(stillOwned()) { "Подготовка оплаты отменена" }
        reservation.get(identity())?.let { return it }
        val before = identity()
        fun checkCurrent() = check(stillOwned() && identity() == before) { "Сеть изменилась. Повторите оплату." }
        if (currentBases.isNotEmpty()) {
            val site = siteAvailable()
            checkCurrent()
            if (site) for (base in currentBases.distinct()) {
                val client = api(base)
                val value = try { preview(client) }
                    catch (cancelled: CancellationException) { throw cancelled }
                    catch (rejection: PaymentApiRejection) { throw rejection }
                    catch (_: Exception) { null }
                checkCurrent()
                if (value != null) return PreparedPaymentRoute(client, value, before).also { reservation.remember(before, it) }
            }
        }
        check(stillOwned()) { "Подготовка оплаты отменена" }
        val (client, value) = temporary()
        check(stillOwned()) { "Подготовка оплаты отменена" }
        val key = identity()
        return PreparedPaymentRoute(client, value, key).also { reservation.remember(key, it) }
    }
}
