package com.silent.vpn.update

import com.silent.vpn.data.UpdateCheckResponse
import com.silent.vpn.policy.OtaCheckPolicy
import com.silent.vpn.policy.OtaGithubDiscovery
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull

/** VPN first; public Pages remains independent of the hive's public IP. Null means retryable failure. */
object OtaUpdateDiscovery {
    suspend fun check(
        onMobileData: Boolean,
        vpnUp: Boolean,
        platform: String,
        currentVersion: String,
        publicJson: suspend () -> String?,
        tunnelCheck: suspend () -> UpdateCheckResponse?,
    ): UpdateCheckResponse? {
        val channel = OtaCheckPolicy.channel(onMobileData, vpnUp)
        if (channel != OtaCheckPolicy.Channel.PUBLIC) {
            val result = attempt { tunnelCheck() }
            if (result != null) return result
            if (!OtaCheckPolicy.allowPublicFallback(onMobileData)) return null
        }
        return attempt {
            when (val offer = OtaGithubDiscovery.parse(publicJson(), platform, currentVersion)) {
                is OtaGithubDiscovery.Result.Available -> UpdateCheckResponse(
                    available = true,
                    version = offer.version,
                    filename = offer.filename,
                    size = offer.size,
                    download_url = offer.downloadUrl,
                    github_download_url = offer.downloadUrl,
                    tunnel_download_url = "/api/updates/download/$platform",
                )
                is OtaGithubDiscovery.Result.Current -> UpdateCheckResponse(available = false)
                OtaGithubDiscovery.Result.Unreadable -> null
            }
        }
    }

    private suspend fun <T> attempt(block: suspend () -> T): T? =
        withTimeoutOrNull(9_000L) {
            try {
                block()
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                null
            }
        }
}
