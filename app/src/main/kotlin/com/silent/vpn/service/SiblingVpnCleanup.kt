package com.silent.vpn.service

import android.content.Context
import android.content.Intent
import com.silent.vpn.policy.SiblingVpnPolicy
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.VpnNetworkHelper
import kotlinx.coroutines.delay

/** Пробуждение sibling-пакета и ожидание снятия чужого VPN перед нашим establish. */
object SiblingVpnCleanup {
    private const val TAG = "SiblingVpnCleanup"

    fun isSiblingInstalled(context: Context): Boolean {
        val sibling = SiblingVpnPolicy.siblingPackage(context.packageName) ?: return false
        return runCatching {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageInfo(sibling, 0)
            true
        }.getOrDefault(false)
    }

    fun requestSiblingTeardown(context: Context) {
        val appCtx = context.applicationContext
        val sibling = SiblingVpnPolicy.siblingPackage(appCtx.packageName) ?: return
        if (!isSiblingInstalled(appCtx)) return
        DebugLog.i(TAG, "request teardown → $sibling")
        runCatching {
            val intent = Intent(SiblingVpnPolicy.ACTION_SIBLING_TEARDOWN).setPackage(sibling)
            appCtx.sendBroadcast(intent)
        }.onFailure { e ->
            DebugLog.w(TAG, "broadcast failed: ${e.message}")
        }
    }

    /**
     * Если в системе висит чужой VPN (часто зомби debug/release) — просим sibling
     * снять TUN и ждём, пока сеть освободится.
     */
    suspend fun clearForeignVpnIfNeeded(context: Context): Boolean {
        val appCtx = context.applicationContext
        if (!VpnNetworkHelper.isOtherVpnActive(appCtx)) return true
        val askSibling = SiblingVpnPolicy.shouldRequestSiblingTeardown(
            ourPackage = appCtx.packageName,
            siblingInstalled = isSiblingInstalled(appCtx),
            otherVpnActive = true,
        )
        if (askSibling) {
            requestSiblingTeardown(appCtx)
        } else {
            DebugLog.i(TAG, "foreign VPN (not sibling) — wait for revoke on establish")
        }
        val attempts = SiblingVpnPolicy.foreignVpnWaitAttempts()
        repeat(attempts) { i ->
            if (!VpnNetworkHelper.isOtherVpnActive(appCtx)) {
                DebugLog.i(TAG, "foreign VPN cleared after ${i * SiblingVpnPolicy.FOREIGN_VPN_POLL_MS}ms")
                return true
            }
            delay(SiblingVpnPolicy.FOREIGN_VPN_POLL_MS)
        }
        DebugLog.w(TAG, "foreign VPN still active after wait — establish may fail")
        return false
    }
}
