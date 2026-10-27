package com.silent.vpn.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.app.PendingIntent
import androidx.core.content.IntentCompat
import com.silent.vpn.policy.SiblingVpnPolicy
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout

/**
 * Другой билд Silent (debug↔release) просит снять наш зомби-VPN после свайпа из недавних.
 * An explicit broadcast alone does not authenticate its sender. Require a
 * system-owned PendingIntent identity created by the expected sibling.
 */
class SiblingVpnTeardownReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != SiblingVpnPolicy.ACTION_SIBLING_TEARDOWN) return
        val proof = runCatching {
            IntentCompat.getParcelableExtra(intent, SiblingVpnPolicy.EXTRA_SENDER_PROOF, PendingIntent::class.java)
        }.getOrNull()
        if (!SiblingVpnPolicy.isTrustedTeardownCreator(context.packageName, proof?.creatorPackage)) {
            DebugLog.w(TAG, "untrusted teardown ignored")
            return
        }
        val pending = goAsync()
        DebugLog.w(TAG, "sibling teardown requested")
        val appCtx = context.applicationContext
        CoroutineScope(Dispatchers.IO).launch {
            try {
                withTimeout(8_000) {
                    VpnConnectHelper.ensureCleanSlate(appCtx, force = true)
                }
                runCatching {
                    appCtx.startService(
                        Intent(appCtx, SilentVpnService::class.java).apply {
                            action = SilentVpnService.ACTION_DISCONNECT
                        },
                    )
                }
            } catch (error: Exception) {
                DebugLog.w(TAG, "sibling cleanup failed: ${error.javaClass.simpleName}")
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        private const val TAG = "SiblingVpnTeardown"
    }
}
