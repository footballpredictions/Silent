package com.silent.vpn.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.silent.vpn.policy.SiblingVpnPolicy
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking

/**
 * Другой билд Silent (debug↔release) просит снять наш зомби-VPN после свайпа из недавних.
 * Receiver exported: доставка только через setPackage(sibling) — чужие приложения не целимся.
 */
class SiblingVpnTeardownReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != SiblingVpnPolicy.ACTION_SIBLING_TEARDOWN) return
        val pending = goAsync()
        DebugLog.w(TAG, "sibling teardown requested")
        try {
            runBlocking(Dispatchers.IO) {
                VpnConnectHelper.ensureCleanSlate(context.applicationContext, force = true)
            }
            runCatching {
                context.applicationContext.startService(
                    Intent(context.applicationContext, SilentVpnService::class.java).apply {
                        action = SilentVpnService.ACTION_DISCONNECT
                    },
                )
            }
        } finally {
            pending.finish()
        }
    }

    companion object {
        private const val TAG = "SiblingVpnTeardown"
    }
}
