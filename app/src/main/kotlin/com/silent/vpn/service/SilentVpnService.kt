package com.silent.vpn.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.silent.vpn.BuildConfig
import com.silent.vpn.MainActivity
import com.silent.vpn.R
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.sync.VpnDataSyncScheduler
import com.silent.vpn.sync.VpnDataSyncBridge
import com.silent.vpn.ui.BrandMarkIcons
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vk.HashParser
import com.silent.vpn.vpn.OlcrtcTunnelManager
import com.silent.vpn.vpn.TunnelApiProxy
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.WireGuardHelper
import com.silent.vpn.vpn.WireGuardConfigBuilder
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import com.silent.vpn.policy.NetworkRecoveryPolicy
import com.silent.vpn.policy.OlcrtcRecoveryPolicy
import com.silent.vpn.policy.VpnNetworkConstants.MIN_TRANSPORT_RESTART_INTERVAL_MS
import dagger.hilt.android.EntryPointAccessors
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.silent.vpn.data.HashItemDto
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * Foreground VPN service — сеть/LTE как в [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android):
 * WakeLock, WifiLock, NetworkCallback (NOT_VPN), pause/resume и restartTransport при смене Wi‑Fi ↔ LTE.
 */
class SilentVpnService : Service() {

    companion object {
        private const val CHANNEL_ID = "silent_vpn_status_v2"
        private const val PREF_NOTIF_CHANNELS_MIGRATED_V2 = "notif_channels_migrated_v2"
        private const val NOTIF_ID = 1001
        private const val NOTIF_OPEN_REQUEST_CODE = 41_001
        /** Небольшой grace после connect, чтобы не дёргать транспорт на старте. */
        private const val NETWORK_GRACE_MS = 12_000L
        /** transportWatchdog не kill сервис, пока libclient ещё стартует. */
        private const val LIBCLIENT_START_GRACE_MS = 45_000L
        /** Минимальный интервал между restartTransport (баланс скорость/стабильность). */
        private const val NETWORK_CHANGE_DEBOUNCE_MS = 1_500L
        /** Задержка перед restart после возврата сети / звонка. */
        private const val NETWORK_RECOVERY_DELAY_MS = 800L
        /** Сколько ждать «больного» транспорта перед restart. */
        private const val TRANSPORT_UNHEALTHY_MS = 20_000L
        /** Нет активных воркеров дольше этого — restart (doze / screen off). */
        private const val TRANSPORT_STALE_MS = 120_000L
        /** Вторая проверка после recovery: трафик должен начать расти (только после полного restart). */
        private const val RECOVERY_VERIFY_DELAY_MS = 4_000L
        private const val RECOVERY_MIN_TRAFFIC_DELTA_MB = 0.05
        /** Не перезапускать libclient повторно, если недавно уже рестартили и транспорт жив. */
        /** Wi‑Fi: сверка подписки пока VPN-сервис жив (даже если UI в фоне). */
        private const val WIFI_SUBSCRIPTION_CHECK_MS = 2 * 60 * 1000L
        private const val NOTIF_UPDATE_MIN_MS = 3_000L
        /** Если CONNECT прилетел повторно сразу после старта, считаем сервис "занятым". */
        private const val CONNECT_BUSY_GRACE_MS = 15_000L
        /** Защита от вечного "подключение…" для CONNECT из плитки при закрытом приложении. */
        private const val TILE_CONNECT_START_TIMEOUT_MS = 35_000L
        const val ACTION_CONNECT = "com.silent.vpn.CONNECT"
        const val ACTION_DISCONNECT = "com.silent.vpn.DISCONNECT"
        /** Другой VPN подключился — Android отозвал наш VpnService. */
        const val ACTION_EXTERNAL_REVOKED = "com.silent.vpn.EXTERNAL_REVOKED"
        const val EXTRA_CONFIG = "vpn_config_json"
        const val EXTRA_IS_BOOTSTRAP = "is_bootstrap"
        /** CONNECT с QS-плитки — полный сброс транспорта перед стартом. */
        const val EXTRA_FROM_TILE = "from_tile"
        var isRunning = false
            private set

        fun resetStaleSession() {
            SessionTrace.mark("SilentVpnService.resetStaleSession")
            isRunning = false
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var connectivityManager: ConnectivityManager? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var lastNetworkChangeTime = 0L
    private var connectStartedAtMs = 0L
    private val activeNetworks = mutableSetOf<Network>()
    private var lastNetworkFingerprint = ""
    private var lastNetworkValidated = true
    private var networkRecoveryJob: Job? = null
    private var recoveryVerifyJob: Job? = null
    private var transportUnhealthySinceMs = 0L
    private var isTunnelPaused = false
    private var pausedForNetwork = false
    private var lastUnderlyingInternet: Boolean? = null
    private var lastMobileDataState: Boolean? = null
    private var phoneCallActive = false
    private var lastTransportRestartMs = 0L
    /** Дедуп LTE↔Wi‑Fi: callback и poll не должны давать два restart подряд. */
    private var lastTransportSwitchMs = 0L
    private var lastTransportSwitchTarget = ""
    private var lastWifiSubscriptionCheckMs = 0L
    private var transportWatchdogJob: Job? = null
    private var statsUpdaterJob: Job? = null
    private var disconnectJob: Job? = null
    private var connectGuardJob: Job? = null
    @Volatile
    private var disconnectEpoch = 0
    @Volatile
    private var tunnelProxyStarted = false
    @Volatile
    private var connectFromTile = false
    @Volatile
    private var dataSyncServiceStarted = false
    /** Активна сессия olcrtc (даже если peer временно упал и идёт reconnect). */
    @Volatile
    private var olcrtcSessionActive = false
    /** tunnelReady хоть раз в этой сессии — recover только после этого. */
    @Volatile
    private var olcrtcEverReady = false
    @Volatile
    private var lastOlcrtcConfigJson: String? = null
    private var olcrtcRecoverJob: Job? = null
    /** Поколение recover: finally старого job не должен сбрасывать флаг нового. */
    private val olcrtcRecoverGen = java.util.concurrent.atomic.AtomicInteger(0)
    /** Пока true — watchdog/peer_dead не стартуют второй recover. */
    @Volatile
    private var olcrtcRecovering = false
    /** Если recover уже идёт — подсказать await wifi/cell при transport_switch. */
    @Volatile
    private var pendingOlcrtcPreferTransport: String? = null
    private var performanceLocksHeld = false
    private var lastNotifUpdateMs = 0L
    private var lastNotifBody = ""
    private var vpnOwnerCallback: ConnectivityManager.NetworkCallback? = null
    private var audioManager: AudioManager? = null
    private var audioModeListener: AudioManager.OnModeChangedListener? = null

    override fun onCreate() {
        super.onCreate()
        SessionTrace.mark("SilentVpnService.onCreate")
        createNotificationChannel()
    }

    private fun isWithinConnectGrace(): Boolean =
        isRunning && System.currentTimeMillis() - connectStartedAtMs < LIBCLIENT_START_GRACE_MS

    private fun isOlcrtcInitialConnectInProgress(): Boolean =
        OlcrtcRecoveryPolicy.isInitialConnectInProgress(
            OlcrtcRecoveryPolicy.InitialConnectInput(
                sessionActive = olcrtcSessionActive,
                everReady = olcrtcEverReady,
                isRunning = isRunning,
                connectStartedAtMs = connectStartedAtMs,
                nowMs = System.currentTimeMillis(),
            ),
        )

    /** Дольше grace на bootstrap — libclient и WG поднимаются медленнее, особенно на TV. */
    private fun networkGraceMs(): Long =
        if (WdttTunnelManager.isBootstrapMode()) 60_000L else NETWORK_GRACE_MS

    private fun recoverySuppressedForRampUp(): Boolean =
        WdttTunnelManager.isBootstrapMode() || WdttTunnelManager.isWorkerRampUpActive()

    /** Как в proxy-turn-vk-android: отдельный цикл обновления уведомления (переживает reconnect). */
    private fun startStatsUpdater() {
        statsUpdaterJob?.cancel()
        statsUpdaterJob = scope.launch {
            SessionTrace.enter("SilentVpnService.statsUpdater")
            delay(300)
            while (isActive) {
                val olcrtcLive =
                    olcrtcSessionActive ||
                        OlcrtcTunnelManager.running.value ||
                        OlcrtcTunnelManager.tunnelReady.value
                if (!WdttTunnelManager.running.value && !olcrtcLive && !isTunnelPaused) {
                    if (!isRunning) {
                        stopSelf()
                        break
                    }
                }
                if (isRunning) {
                    val stats = WdttTunnelManager.stats.value
                    if (WdttTunnelManager.tunnelReady.value) {
                        connectGuardJob?.cancel()
                        ensureSessionWakeLock()
                        if (!VpnServiceTracker.isSessionMarkedActive(this@SilentVpnService)) {
                            VpnServiceTracker.markSessionActive(this@SilentVpnService, true)
                        }
                        ensureTunnelApiProxyAsync()
                        if (!WdttTunnelManager.isBootstrapMode() && !dataSyncServiceStarted) {
                            runCatching { VpnDataSyncScheduler.onMainVpnConnected(applicationContext) }
                            dataSyncServiceStarted = true
                        }
                        postVpnNotification(stats)
                        VpnTileHelper.requestUpdate(this@SilentVpnService)
                        checkTransportHealth()
                        checkUnderlyingNetwork()
                        maybeRefreshWifiSubscription()
                    } else if (olcrtcLive) {
                        // Wi‑Fi↔LTE для olcrtc: раньше poll не вызывался (только WDTT ready).
                        connectGuardJob?.cancel()
                        ensureSessionWakeLock()
                        checkUnderlyingNetwork()
                        if (OlcrtcTunnelManager.tunnelReady.value) {
                            postVpnNotification("olcrtc · туннель активен")
                            VpnTileHelper.requestUpdate(this@SilentVpnService)
                        } else {
                            startFg(buildConnectingNotification())
                        }
                    } else if (WdttTunnelManager.running.value) {
                        startFg(buildConnectingNotification())
                    }
                }
                delay(2000)
            }
            SessionTrace.exit("SilentVpnService.statsUpdater")
        }
    }

    /** Wi‑Fi + main VPN: public /api/users/me — rev подписки на сервере не меняется при истечении. */
    private fun maybeRefreshWifiSubscription() {
        if (WdttTunnelManager.isBootstrapMode()) return
        if (VpnNetworkHelper.isOnMobileData(this)) return
        val now = System.currentTimeMillis()
        if (now - lastWifiSubscriptionCheckMs < WIFI_SUBSCRIPTION_CHECK_MS) return
        lastWifiSubscriptionCheckMs = now
        scope.launch(Dispatchers.IO) {
            runCatching {
                val repo = EntryPointAccessors.fromApplication(
                    applicationContext,
                    AppEntryPoint::class.java,
                ).silentRepository()
                if (!repo.isLoggedIn()) return@runCatching
                val profile = repo.fetchProfileLive().getOrNull() ?: return@runCatching
                repo.saveCachedProfile(profile)
                VpnDataSyncBridge.configSyncListener?.onProfile(profile)
                    ?: DebugLog.i("VpnService", "wifi subscription cached active=${profile.subscription.is_active}")
            }.onFailure { e ->
                DebugLog.w("VpnService", "wifi subscription check: ${e.message}")
            }
        }
    }

    /** Локальный прокси — только Wi‑Fi fallback; LTE: direct 10.66.66.1 через mobileApiRoute. */
    private fun ensureTunnelApiProxyAsync() {
        if (WdttTunnelManager.isBootstrapMode()) return
        if (VpnNetworkHelper.isOnMobileData(this)) return
        if (TunnelApiProxy.isActive()) return
        scope.launch(Dispatchers.IO) {
            runCatching {
                val repo = EntryPointAccessors.fromApplication(
                    applicationContext,
                    AppEntryPoint::class.java,
                ).silentRepository()
                repo.ensureTunnelApiProxy()
            }.onFailure { e ->
                DebugLog.w("VpnService", "tunnel proxy start: ${e.message}")
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        SessionTrace.mark("SilentVpnService.onStartCommand", "action=${intent?.action}")
        when (intent?.action) {
            ACTION_CONNECT -> {
                val configJson = intent.getStringExtra(EXTRA_CONFIG)
                if (configJson == null) {
                    SessionTrace.warn("SilentVpnService.CONNECT", "no config")
                    DebugLog.e("VpnService", "CONNECT without config")
                    stopSelf()
                    return START_NOT_STICKY
                }
                if (VpnTileConnect.isCaptchaPending()) {
                    SessionTrace.mark("SilentVpnService.CONNECT", "blocked captcha")
                    DebugLog.w("VpnService", "CONNECT ignored — VK captcha in progress")
                    ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(this)
                    return START_STICKY
                }
                try {
                    acquirePerformanceLocks()
                    startFg(buildConnectingNotification())
                } catch (e: Exception) {
                    SessionTrace.warn("SilentVpnService.CONNECT", "FGS failed: ${e.message}")
                    DebugLog.e("VpnService", "CONNECT FGS failed", e)
                    performanceLocksHeld = false
                    releaseWakeLock()
                    releaseWifiLock()
                    stopSelf()
                    return START_NOT_STICKY
                }
                disconnectEpoch++
                disconnectJob?.cancel()
                connectFromTile = intent.getBooleanExtra(EXTRA_FROM_TILE, false)
                runBlocking(Dispatchers.IO) {
                    disconnectJob?.join()
                    if (connectFromTile) {
                        VpnConnectHelper.prepareForTileReconnect(this@SilentVpnService)
                    } else {
                        VpnConnectHelper.prepareForConnect(this@SilentVpnService)
                    }
                }
                if (isRunning) {
                    val withinGrace =
                        System.currentTimeMillis() - connectStartedAtMs < CONNECT_BUSY_GRACE_MS
                    // olcrtc running без ready после grace = мёртвый peer — не блокируем плитку.
                    val olcrtcBusy =
                        OlcrtcTunnelManager.tunnelReady.value ||
                            (OlcrtcTunnelManager.running.value && withinGrace)
                    val busy = WdttTunnelManager.running.value ||
                        WdttTunnelManager.tunnelReady.value ||
                        olcrtcBusy ||
                        VpnSessionState.isActive() ||
                        withinGrace
                    if (!busy) {
                        // После падения/убитого транспорта флаг isRunning мог остаться true,
                        // и плитка больше не могла инициировать новый CONNECT.
                        SessionTrace.warn("SilentVpnService.CONNECT", "stale isRunning reset")
                        DebugLog.w("VpnService", "stale isRunning=true without active transport; reset")
                        isRunning = false
                        olcrtcSessionActive = false
                        VpnServiceTracker.markSessionActive(this, false)
                    }
                }
                if (isRunning) {
                    SessionTrace.mark(
                        "SilentVpnService.CONNECT",
                        if (WdttTunnelManager.tunnelReady.value) "ignored — already connected"
                        else "ignored — already connecting",
                    )
                    VpnTileHelper.requestUpdate(this)
                    return START_STICKY
                }
                SessionTrace.enter(
                    "SilentVpnService.CONNECT",
                    "device=${runCatching { JSONObject(configJson).optString("device_id") }.getOrNull()?.take(8)}",
                )
                connectStartedAtMs = System.currentTimeMillis()
                lastNetworkChangeTime = 0L
                lastNetworkFingerprint = ""
                lastNetworkValidated = true
                transportUnhealthySinceMs = 0L
                phoneCallActive = false
                pausedForNetwork = false
                lastUnderlyingInternet = null
                lastMobileDataState = null
                lastTransportRestartMs = 0L
                lastWifiSubscriptionCheckMs = 0L
                lastNotifUpdateMs = 0L
                tunnelProxyStarted = false
                setupNetworkCallback()
                setupPhoneCallMonitor()
                startTransportWatchdog()
                startStatsUpdater()
                startConnectGuardIfNeeded()
                try {
                    setupVpnOwnershipMonitor()
                    connect(configJson, intent.getBooleanExtra(EXTRA_IS_BOOTSTRAP, false))
                } catch (e: Exception) {
                    SessionTrace.warn("SilentVpnService.CONNECT", "startup failed: ${e.message}")
                    DebugLog.e("VpnService", "CONNECT startup failed", e)
                    isRunning = false
                    performanceLocksHeld = false
                    releaseWakeLock()
                    releaseWifiLock()
                    clearVpnNotification()
                    stopSelf()
                    return START_NOT_STICKY
                }
                VpnTileHelper.requestUpdate(this)
            }
            ACTION_DISCONNECT -> {
                SessionTrace.enter("SilentVpnService.DISCONNECT")
                if (
                    !isRunning &&
                    !WdttTunnelManager.running.value &&
                    !OlcrtcTunnelManager.running.value &&
                    !olcrtcSessionActive
                ) {
                    stopSelf()
                    return START_NOT_STICKY
                }
                disconnect()
            }
            ACTION_EXTERNAL_REVOKED -> {
                SessionTrace.warn("SilentVpnService", "EXTERNAL_REVOKED")
                DebugLog.w("VpnService", "DISCONNECT — VPN revoked by another app (full teardown)")
                // Даже при stale isRunning — гасим FGS + libclient (иначе два уведомления debug/release).
                if (isRunning || WdttTunnelManager.running.value) {
                    disconnect()
                } else {
                    clearVpnNotification()
                    VpnServiceTracker.markSessionActive(this, false)
                    scope.launch(Dispatchers.IO) {
                        runCatching { VpnConnectHelper.ensureCleanSlate(this@SilentVpnService, force = true) }
                        withContext(Dispatchers.Main) {
                            clearVpnNotification()
                            stopSelf()
                        }
                    }
                }
            }
            null -> {
                // После force-kill pref мог остаться true — не restore, только cleanup.
                SessionTrace.mark("SilentVpnService.onStartCommand", "STICKY after kill — cleanup")
                VpnConnectHelper.ensureCleanSlate(this)
                stopSelf()
                return START_NOT_STICKY
            }
        }
        return START_STICKY
    }

    private fun connect(configJson: String, forceBootstrap: Boolean = false) {
        try {
            val obj = JSONObject(configJson)
            val bypassFamily = obj.optString("bypass_family", obj.optString("bypassFamily", "wdtt"))
            if (bypassFamily.equals("olcrtc", ignoreCase = true)) {
                SilentRepository.APP_EXCLUDED_FROM_VPN = true
                lastOlcrtcConfigJson = configJson
                olcrtcSessionActive = true
                olcrtcEverReady = false
                lastTransportRestartMs = System.currentTimeMillis()
                OlcrtcTunnelManager.setSessionDeadHandler { reason ->
                    if (isOlcrtcInitialConnectInProgress()) return@setSessionDeadHandler
                    scheduleNetworkRecovery("olcrtc_peer_dead:$reason", 1_200L)
                }
                // TUN через отдельный VpnService (этот класс — обычный Service).
                startService(
                    Intent(this, OlcrtcVpnService::class.java).apply {
                        action = OlcrtcVpnService.ACTION_START
                        putExtra(OlcrtcVpnService.EXTRA_CONFIG, configJson)
                    },
                )
                DebugLog.i("VpnService", "olcrtc path → OlcrtcVpnService")
                isRunning = true
                SessionTrace.mark("SilentVpnService.connect", "isRunning=true olcrtc")
                dataSyncServiceStarted = false
                startFg(buildConnectingNotification())
                watchOlcrtcReadyNotification()
                VpnTileHelper.requestUpdate(this)
                return
            }

            val hashes = mutableListOf<String>()
            val arr = obj.optJSONArray("vk_hashes")
            if (arr != null) for (i in 0 until arr.length()) hashes.add(arr.getString(i))

            val deviceId = obj.optString("device_id").ifBlank {
                obj.optString("deviceId").ifBlank { "android" }
            }

            val vpnConfig = runCatching { Gson().fromJson(configJson, VpnConfig::class.java) }.getOrNull()
            val dnsOverride = if (BuildConfig.DEBUG) {
                runCatching {
                    EntryPointAccessors.fromApplication(
                        applicationContext,
                        AppEntryPoint::class.java,
                    ).silentRepository().dnsServersForVpn()
                }.getOrNull()
            } else {
                null
            }
            // apiWg — fallback если GETCONF не пришёл за ~22 с (не ранний подъём WG).
            val apiWg = vpnConfig?.let { WireGuardConfigBuilder.fromVpnConfig(it, dnsOverride = dnsOverride) }

            val bootHash = EntryPointAccessors.fromApplication(
                applicationContext,
                AppEntryPoint::class.java,
            ).silentRepository().getBootstrapHash()?.trim().orEmpty()
            val isBootstrap = forceBootstrap || deviceId.startsWith("boot:")
            val rawHashes = HashParser.normalizeList(hashes).filter { it.isNotBlank() }.distinct()
            val savedServerHashes = if (isBootstrap) emptyList() else loadSavedServerHashes()
            val wdttHashes = when {
                isBootstrap -> {
                    val h = rawHashes.firstOrNull { it.isNotBlank() }
                        ?: bootHash.takeIf { it.isNotBlank() }
                    listOfNotNull(h?.trim()?.takeIf { it.isNotBlank() })
                }
                savedServerHashes.isNotEmpty() -> savedServerHashes
                else -> rawHashes
                    .filter { bootHash.isEmpty() || it != bootHash }
                    .take(HashChannelHelper.MAX_HASHES)
            }
            val savedActive = loadSavedActiveServerHashCount()
            val activeHashCount = if (isBootstrap) {
                1
            } else {
                maxOf(wdttHashes.size, savedActive, 1).coerceAtMost(HashChannelHelper.MAX_HASHES)
            }
            // GETCONF: device_id из конфига (boot:fp / UUID backend). Не ANDROID_ID — на Silent VPS
            // пул 10.66.66.2–250; новый id при исчерпании пула → NOCONF.
            val libclientDeviceId = deviceId
            // Bootstrap: app в туннеле. Main: app вне WG.
            SilentRepository.APP_EXCLUDED_FROM_VPN = !isBootstrap
            DebugLog.i(
                "VpnService",
                "VPN app excluded=${SilentRepository.APP_EXCLUDED_FROM_VPN} mobile=${VpnNetworkHelper.isOnMobileData(this)} bootstrap=$isBootstrap",
            )
            val totalWorkers = if (isBootstrap) {
                HashChannelHelper.WORKERS_PER_GROUP
            } else {
                val configWorkers = vpnConfig?.stream_count?.takeIf {
                    it >= HashChannelHelper.WORKERS_PER_GROUP
                }
                if (configWorkers != null) {
                    HashChannelHelper.workersForLibclient(configWorkers, activeHashCount)
                } else {
                    repoResolveTotalWorkers(activeHashCount)
                }
            }
            val libclientHashes = if (isBootstrap) {
                wdttHashes.firstOrNull { it.isNotBlank() }?.let { listOf(it.trim()) } ?: emptyList()
            } else {
                HashChannelHelper.hashesForLibclient(wdttHashes, totalWorkers)
            }

            // Кеш-WG из плитки иногда залипает в состоянии Active=0 без реального транспорта.
            // Для стабильности всегда ждём рабочий GETCONF/воркеры.
            val fastWgCache = false
            if (connectFromTile) {
                DebugLog.i(
                    "VpnService",
                    "tile connect fastWg=$fastWgCache apiWg=${!apiWg.isNullOrBlank()}",
                )
            }

            val vkCred = EntryPointAccessors.fromApplication(
                applicationContext,
                AppEntryPoint::class.java,
            ).silentRepository().resolveVkCredLaunchParams()

            WdttTunnelManager.traceApp(
                "service_connect",
                "SilentVpnService connect bootstrap=$isBootstrap workers=$totalWorkers hashes=${libclientHashes.size}",
            )
            WdttTunnelManager.start(
                this,
                WdttTunnelManager.Params(
                    serverIp = obj.getString("server_ip"),
                    serverPort = obj.getInt("server_port"),
                    vkHashes = libclientHashes.ifEmpty { wdttHashes },
                    wdttPassword = obj.getString("wdtt_password"),
                    deviceId = libclientDeviceId,
                    workers = totalWorkers,
                    activeHashCount = activeHashCount,
                    captchaMode = vkCred.captchaMode,
                    vkAuthMode = vkCred.vkAuthMode,
                    apiWgConfig = apiWg,
                    isBootstrap = isBootstrap,
                    fastWgCache = fastWgCache,
                ),
                isSwitching = false,
            )
            DebugLog.i(
                "VpnService",
                "WDTT n=$totalWorkers vk=${libclientHashes.size}/$activeHashCount hashes",
            )
            isRunning = true
            SessionTrace.mark("SilentVpnService.connect", "isRunning=true")
            dataSyncServiceStarted = false
            VpnTileHelper.requestUpdate(this)
        } catch (e: Exception) {
            SessionTrace.warn("SilentVpnService.connect", e.message ?: "failed")
            DebugLog.e("VpnService", "connect failed", e)
            isRunning = false
            VpnTileHelper.requestUpdate(this)
            releaseWakeLock()
            releaseWifiLock()
            clearVpnNotification()
            stopSelf()
        }
    }

    private fun disconnect() {
        if (
            !isRunning &&
            !WdttTunnelManager.running.value &&
            !OlcrtcTunnelManager.running.value &&
            !olcrtcSessionActive
        ) {
            VpnTileHelper.requestUpdate(this)
            stopSelf()
            return
        }
        DebugLog.i("VpnService", "DISCONNECT")
        val epoch = ++disconnectEpoch
        disconnectJob?.cancel()
        connectGuardJob?.cancel()
        olcrtcRecoverGen.incrementAndGet()
        olcrtcRecoverJob?.cancel()
        olcrtcRecovering = false
        pendingOlcrtcPreferTransport = null
        isRunning = false
        olcrtcSessionActive = false
        olcrtcEverReady = false
        lastOlcrtcConfigJson = null
        OlcrtcTunnelManager.setSessionDeadHandler(null)
        SessionTrace.mark("SilentVpnService.disconnect", "isRunning=false epoch=$epoch")
        VpnServiceTracker.markSessionActive(this, false)
        teardownVpnOwnershipMonitor()
        VpnTileHelper.requestUpdate(this)
        transportWatchdogJob?.cancel()
        networkRecoveryJob?.cancel()
        recoveryVerifyJob?.cancel()
        statsUpdaterJob?.cancel()
        isTunnelPaused = false
        activeNetworks.clear()
        lastNetworkFingerprint = ""
        lastNetworkValidated = true
        transportUnhealthySinceMs = 0L
        phoneCallActive = false
        pausedForNetwork = false
        lastUnderlyingInternet = null
        lastMobileDataState = null
        lastTransportRestartMs = 0L
        performanceLocksHeld = false
        lastNotifBody = ""
        lastNotifUpdateMs = 0L
        teardownNetworkCallback()
        teardownPhoneCallMonitor()
        clearVpnNotification()
        VpnBackendSync.stop()
        runCatching { VpnDataSyncScheduler.onMainVpnDisconnected(applicationContext) }
        dataSyncServiceStarted = false
        tunnelProxyStarted = false
        disconnectJob = scope.launch(Dispatchers.IO) {
            try {
                val repo = EntryPointAccessors.fromApplication(
                    applicationContext,
                    AppEntryPoint::class.java,
                ).silentRepository()
                val notifyJob = if (repo.isLoggedIn() && WdttTunnelManager.tunnelReady.value) {
                    async {
                        runCatching { VpnBackendSync.notifyDisconnect(this@SilentVpnService) }
                    }
                } else {
                    null
                }
                withTimeoutOrNull(1_500L) { notifyJob?.await() }
                if (epoch != disconnectEpoch) {
                    SessionTrace.mark("SilentVpnService.disconnect", "superseded — tile reconnect")
                    return@launch
                }
                SilentRepository.APP_EXCLUDED_FROM_VPN = true
                OlcrtcTunnelManager.stop()
                runCatching {
                    startService(
                        Intent(this@SilentVpnService, OlcrtcVpnService::class.java).apply {
                            action = OlcrtcVpnService.ACTION_STOP
                        },
                    )
                }
                WdttTunnelManager.prepareForShutdown()
                if (isRunning) {
                    SessionTrace.mark("SilentVpnService.disconnect", "skipped teardown — reconnected")
                    return@launch
                }
                WdttTunnelManager.stopAndAwait()
                if (epoch != disconnectEpoch || isRunning) {
                    SessionTrace.mark("SilentVpnService.disconnect", "skip stopSelf — reconnect")
                    return@launch
                }
                runCatching { WireGuardHelper(this@SilentVpnService).forceStopSilentTunnel() }
                withContext(Dispatchers.Main) {
                    if (isRunning) return@withContext
                    releaseWakeLock()
                    releaseWifiLock()
                    stopSelf()
                }
            } catch (e: CancellationException) {
                SessionTrace.mark("SilentVpnService.disconnect", "cancelled")
                throw e
            }
        }
    }

    /** Убрать уведомление из шторки — только когда VPN выключен (только main thread). */
    private fun clearVpnNotification() {
        runCatching {
            stopForeground(STOP_FOREGROUND_REMOVE)
            getSystemService(NotificationManager::class.java)?.cancel(NOTIF_ID)
        }
    }

    private fun setupNetworkCallback() {
        if (networkCallback != null) return
        connectivityManager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        activeNetworks.clear()
        // Underlying NOT_VPN — не default/VPN (иначе Wi‑Fi↔LTE не видно при живом туннеле).
        lastNetworkFingerprint = VpnNetworkHelper.underlyingTransportFingerprint(this)
        lastNetworkValidated = VpnNetworkHelper.hasUnderlyingInternet(this)
        lastUnderlyingInternet = lastNetworkValidated
        lastMobileDataState = VpnNetworkHelper.isOnMobileData(this)
        networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                activeNetworks.add(network)
                maybeRecoverOnUnderlyingChange("available")
            }

            override fun onLost(network: Network) {
                activeNetworks.remove(network)
                // Wi‑Fi выкл при живом LTE: cell уже в activeNetworks — без этого fingerprint
                // остаётся "wifi" и transport_switch не приходит.
                maybeRecoverOnUnderlyingChange("lost")
            }

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) return
                if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) return
                val validated = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                    caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
                } else {
                    true
                }
                if (validated != lastNetworkValidated) {
                    val wasValidated = lastNetworkValidated
                    lastNetworkValidated = validated
                    if (!wasValidated && validated && isRunning) {
                        scheduleNetworkRecovery("validated")
                    }
                }
                maybeRecoverOnUnderlyingChange("capabilities")
            }
        }
        // Всегда NOT_VPN: default callback при VPN = сеть туннеля → wifi/cell не детектятся.
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()
        connectivityManager?.registerNetworkCallback(request, networkCallback!!)
    }

    /** Сверка underlying fingerprint (wifi/cell) и schedule transport_switch / restored. */
    private fun maybeRecoverOnUnderlyingChange(source: String) {
        if (!isRunning) return
        if (isOlcrtcInitialConnectInProgress()) return
        val fp = VpnNetworkHelper.underlyingTransportFingerprint(this)
        val validated = VpnNetworkHelper.hasUnderlyingInternet(this)
        if (fp.isEmpty()) {
            // Дыра wifi↔cell: НЕ сбрасывать fingerprint — иначе не будет transport_switch.
            DebugLog.i("VpnService", "underlying $source: blackout (keep fp=$lastNetworkFingerprint)")
            scheduleNetworkRecovery("underlying_blackout", 1_500L)
            return
        }
        if (lastNetworkFingerprint.isEmpty()) {
            lastNetworkFingerprint = fp
            if (validated) {
                scheduleNetworkRecovery("${source}_restored:$fp", 800L)
            }
            return
        }
        if (fp == lastNetworkFingerprint) return
        val old = lastNetworkFingerprint
        lastNetworkFingerprint = fp
        val switch = wifiCellTransportTarget(old, fp)
        if (switch != null) {
            DebugLog.i("VpnService", "underlying $source: $old → $fp → transport_switch:$switch")
            // Старт recover сразу, внутри ждём VALIDATED нужного транспорта.
            scheduleNetworkRecovery("transport_switch:$switch", 400L)
        } else if (validated) {
            scheduleNetworkRecovery("$source:$fp")
        }
    }

    private fun currentDefaultNetworkFingerprint(): String =
        VpnNetworkHelper.underlyingTransportFingerprint(this)

    private fun fingerprintForNetwork(network: Network): String {
        val cm = connectivityManager ?: return ""
        return networkFingerprint(cm.getNetworkCapabilities(network))
    }

    /** Только тип транспорта default-сети — без VALIDATED (Android часто мигает v0↔v1 на том же Wi‑Fi). */
    private fun networkFingerprint(caps: NetworkCapabilities?): String {
        if (caps == null) return ""
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "eth"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cell"
            else -> "unknown"
        }
    }

    /** cell↔wifi — один transport_switch; available/capabilities не дублируют restart. */
    private fun wifiCellTransportTarget(oldFp: String, newFp: String): String? =
        NetworkRecoveryPolicy.wifiCellTransportTarget(oldFp, newFp)

    private fun scheduleNetworkRecovery(reason: String, delayMs: Long = NETWORK_RECOVERY_DELAY_MS) {
        if (!isRunning) return
        networkRecoveryJob?.cancel()
        networkRecoveryJob = scope.launch {
            delay(delayMs)
            requestNetworkRecovery(reason)
        }
    }

    private fun requestNetworkRecovery(reason: String) {
        val olcrtcPath = olcrtcSessionActive ||
            lastOlcrtcConfigJson != null ||
            OlcrtcTunnelManager.running.value ||
            OlcrtcTunnelManager.tunnelReady.value
        if (!olcrtcPath && WdttTunnelManager.isNetworkRecoverySuppressed()) {
            // Если в момент события идёт WG/overlay transition, не теряем recovery-сигнал.
            scheduleNetworkRecovery("$reason:suppressed", 1_200L)
            return
        }
        if (!isRunning) return
        if (OlcrtcRecoveryPolicy.shouldSkipNetworkRecoveryDuringInitialConnect(
                isOlcrtcInitialConnectInProgress(),
                reason,
            )
        ) {
            DebugLog.i("VpnService", "recovery skipped — olcrtc initial connect ($reason)")
            return
        }
        if (NetworkRecoveryPolicy.shouldDeferRecoveryForPhoneCall(phoneCallActive)) return
        // peer_dead / phone_call / wifi↔lte — не режем grace (иначе после смены сети «залипает»).
        val skipGrace =
            reason.startsWith("olcrtc_peer_dead") ||
                reason.startsWith("phone_call_end") ||
                reason.startsWith("watchdog_olcrtc") ||
                reason.startsWith("transport_switch:") ||
                reason.startsWith("underlying_blackout") ||
                reason.startsWith("internet_restored")
        if (!skipGrace && System.currentTimeMillis() - connectStartedAtMs < networkGraceMs()) return
        if (reason.startsWith("underlying_blackout")) {
            // Только пауза при полной дыре; switch ждём когда fp снова появится.
            if (!VpnNetworkHelper.hasAnyUnderlyingInternet(this)) {
                if (!pausedForNetwork) {
                    pausedForNetwork = true
                    isTunnelPaused = true
                }
            }
            return
        }
        if (lastNetworkFingerprint.isEmpty()) {
            val fp = currentDefaultNetworkFingerprint()
            if (fp.isEmpty() && !skipGrace && !reason.startsWith("internet_restored")) return
            if (fp.isNotEmpty()) lastNetworkFingerprint = fp
        }
        val now = System.currentTimeMillis()
        val sinceLast = now - lastNetworkChangeTime
        if (sinceLast < NETWORK_CHANGE_DEBOUNCE_MS) {
            scheduleNetworkRecovery(reason, NETWORK_CHANGE_DEBOUNCE_MS - sinceLast)
            return
        }
        lastNetworkChangeTime = now
        recoverTransportAfterNetwork(reason)
    }

    private fun recoverTransportAfterNetwork(reason: String) {
        pausedForNetwork = false
        isTunnelPaused = false
        DebugLog.i("VpnService", "network recovery: $reason")
        if (
            olcrtcSessionActive ||
            lastOlcrtcConfigJson != null ||
            OlcrtcTunnelManager.running.value ||
            OlcrtcTunnelManager.tunnelReady.value
        ) {
            recoverOlcrtcAfterNetwork(reason)
            return
        }
        // Bootstrap / login: не убиваем libclient — иначе вход «крутится», API 10.66.66.1 недоступен.
        if (WdttTunnelManager.isBootstrapMode()) {
            if (!WdttTunnelManager.running.value || !WdttTunnelManager.tunnelReady.value) {
                WdttTunnelManager.resume()
            } else {
                WdttTunnelManager.reapplyWireGuardForNetworkChange(applicationContext)
            }
            return
        }
        val trafficBeforeMb = currentTrafficMb()
        scope.launch(Dispatchers.IO) {
            if (!WdttTunnelManager.isBootstrapMode() && SilentRepository.APP_EXCLUDED_FROM_VPN) {
                runCatching {
                    val repo = EntryPointAccessors.fromApplication(
                        applicationContext,
                        AppEntryPoint::class.java,
                    ).silentRepository()
                    repo.invalidatePublicReachabilityCache()
                    if (VpnNetworkHelper.isOnMobileData(this@SilentVpnService)) {
                        TunnelApiProxy.stopAndAwait()
                        repo.prepareMainVpnDirectApi()
                    } else {
                        TunnelApiProxy.stopAndAwait()
                        repo.ensureTunnelApiProxy()
                    }
                }.onFailure { e ->
                    DebugLog.w("VpnService", "tunnel API restart: ${e.message}")
                }
            }
        }
        if (!WdttTunnelManager.running.value || !WdttTunnelManager.tunnelReady.value) {
            DebugLog.w("VpnService", "network recovery: transport down, resume")
            WdttTunnelManager.resume()
            scheduleRecoveryVerification("resume:$reason", trafficBeforeMb)
            return
        }
        val activeWorkers = WdttTunnelManager.activeWorkers.value
        // LTE↔Wi‑Fi: transport_switch — всегда полный restart libclient (fast-path ломал домашний Wi‑Fi).
        val canFastSwitch =
            activeWorkers > 0 &&
                !reason.startsWith("transport_switch:") &&
                (reason.startsWith("available:") ||
                    reason.startsWith("capabilities:") ||
                    reason.startsWith("validated") ||
                    reason.startsWith("internet_restored"))
        if (canFastSwitch) {
            // Стабильный Wi‑Fi: не перезапускаем libclient без смены транспорта.
            WdttTunnelManager.reapplyWireGuardForNetworkChange(applicationContext)
            return
        }
        if (shouldSkipTransportRestart(reason)) {
            DebugLog.i("VpnService", "network recovery: skip libclient restart ($reason)")
            WdttTunnelManager.reapplyWireGuardForNetworkChange(applicationContext)
            return
        }
        if (reason.startsWith("transport_switch:")) {
            val target = reason.removePrefix("transport_switch:")
            val now = System.currentTimeMillis()
            if (target == lastTransportSwitchTarget && now - lastTransportSwitchMs < 30_000L) {
                DebugLog.i("VpnService", "transport switch duplicate ($target) — skip second restart")
                WdttTunnelManager.reapplyWireGuardForNetworkChange(applicationContext)
                return
            }
            lastTransportSwitchTarget = target
            lastTransportSwitchMs = now
            // Ждём VALIDATED wifi/cell до restart libclient (иначе handshake timeout).
            scope.launch(Dispatchers.IO) {
                val prefer = if (target == "wifi") "wifi" else "cell"
                WdttTunnelManager.logUi("net_wait", "ждём готовность сети ($prefer)…", 2)
                val ok = VpnNetworkHelper.awaitUnderlyingReady(
                    this@SilentVpnService,
                    timeoutMs = 20_000L,
                    preferTransport = prefer,
                )
                if (!isRunning || !ok) {
                    DebugLog.w("VpnService", "wdtt transport switch deferred — net not ready")
                    scheduleNetworkRecovery("internet_restored", 2_500L)
                    return@launch
                }
                lastTransportRestartMs = System.currentTimeMillis()
                WdttTunnelManager.restartTransportAfterNetwork()
                WdttTunnelManager.reapplyWireGuardForNetworkChange(applicationContext)
                scheduleRecoveryVerification("restart:$reason", trafficBeforeMb)
            }
            return
        }
        lastTransportRestartMs = System.currentTimeMillis()
        WdttTunnelManager.restartTransportAfterNetwork()
        WdttTunnelManager.reapplyWireGuardForNetworkChange(applicationContext)
        scheduleRecoveryVerification("restart:$reason", trafficBeforeMb)
    }

    /**
     * peer_dead / watchdog: сброс sticky + новый room в JSON (кеш не сносим при fail fetch).
     */
    private suspend fun refreshOlcrtcConfigJson(oldJson: String, reason: String): String {
        return try {
            val repo = EntryPointAccessors.fromApplication(
                applicationContext,
                AppEntryPoint::class.java,
            ).silentRepository()
            val next = repo.reportOlcrtcRoomFailure(reason)
                ?: repo.resolveOlcrtcConfig(preferCache = true)
                ?: return oldJson
            val provider = repo.getOlcrtcProvider()
            val p = next.providers[provider] ?: return oldJson
            if (p.room.isBlank() || next.crypto_key.length != 64) return oldJson
            val obj = JSONObject(oldJson)
            val prevRoom = obj.optString("olcrtc_room", "")
            obj.put("olcrtc_room", p.room)
            obj.put("olcrtc_crypto_key", next.crypto_key)
            obj.put("olcrtc_provider", provider)
            obj.put("olcrtc_transport", p.transport.ifBlank { obj.optString("olcrtc_transport", "datachannel") })
            if (p.auth_token.isNotBlank()) {
                obj.put("olcrtc_auth_token", p.auth_token)
            }
            if (prevRoom.isNotBlank() && prevRoom != p.room) {
                WdttTunnelManager.logUi(
                    "olcrtc_reassign",
                    "новый канал: ${p.room.take(48)}",
                    1,
                )
            }
            obj.toString()
        } catch (e: Exception) {
            DebugLog.w("VpnService", "refreshOlcrtcConfigJson: ${e.message}")
            oldJson
        }
    }

    private fun isOlcrtcRecoverInFlight(): Boolean =
        olcrtcRecovering || (olcrtcRecoverJob?.isActive == true)

    /** Полный restart olcrtc peer (звонок / Wi‑Fi↔LTE / peer closed / потеря сигнала). */
    private fun recoverOlcrtcAfterNetwork(reason: String) {
        val cfg = lastOlcrtcConfigJson ?: OlcrtcTunnelManager.lastConfigJson()
        val preferFromReason = OlcrtcRecoveryPolicy.preferTransportFromReason(reason)
        val now = System.currentTimeMillis()
        val decision = OlcrtcRecoveryPolicy.decideRecover(
            OlcrtcRecoveryPolicy.RecoverInput(
                configJson = cfg,
                isRunning = isRunning,
                everReady = olcrtcEverReady,
                recoverInFlight = isOlcrtcRecoverInFlight(),
                reason = reason,
                preferFromReason = preferFromReason,
                lastTransportSwitchTarget = lastTransportSwitchTarget,
                lastTransportSwitchMs = lastTransportSwitchMs,
                lastTransportRestartMs = lastTransportRestartMs,
                nowMs = now,
            ),
        )
        when (decision) {
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NO_CONFIG -> {
                DebugLog.w("VpnService", "olcrtc recovery skipped — no config ($reason)")
                return
            }
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NOT_RUNNING -> return
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NEVER_READY -> {
                DebugLog.i("VpnService", "olcrtc recovery skipped — never was ready ($reason)")
                return
            }
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_IN_FLIGHT -> {
                if (preferFromReason != null) {
                    pendingOlcrtcPreferTransport = preferFromReason
                }
                DebugLog.i("VpnService", "olcrtc recovery already in flight — skip $reason")
                return
            }
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_SWITCH_DUP -> {
                DebugLog.i(
                    "VpnService",
                    "olcrtc transport switch duplicate ($preferFromReason) — skip",
                )
                return
            }
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_DEBOUNCE -> {
                DebugLog.i("VpnService", "olcrtc recovery debounce ($reason)")
                return
            }
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW -> Unit
        }
        if (preferFromReason != null) {
            lastTransportSwitchTarget = preferFromReason
            lastTransportSwitchMs = now
            pendingOlcrtcPreferTransport = preferFromReason
        }
        lastTransportRestartMs = now
        lastOlcrtcConfigJson = cfg
        olcrtcSessionActive = true
        pausedForNetwork = false
        isTunnelPaused = false
        DebugLog.i("VpnService", "olcrtc recovery: $reason")
        WdttTunnelManager.logUi("olcrtc_recover", "переподключение: $reason", 2)
        startFg(buildConnectingNotification())
        VpnTileHelper.requestUpdate(this)
        val epoch = disconnectEpoch
        val myGen = olcrtcRecoverGen.incrementAndGet()
        olcrtcRecovering = true
        olcrtcRecoverJob = scope.launch(Dispatchers.IO) {
            try {
                OlcrtcTunnelManager.suppressPeerDeadFor(45_000L)
                OlcrtcTunnelManager.setSessionDeadHandler { r ->
                    if (r.startsWith("process_exit_early")) return@setSessionDeadHandler
                    if (isOlcrtcRecoverInFlight()) return@setSessionDeadHandler
                    if (isOlcrtcInitialConnectInProgress()) return@setSessionDeadHandler
                    scheduleNetworkRecovery("olcrtc_peer_dead:$r", 2_500L)
                }
                // 1) Снять мёртвый TUN сразу — иначе 0.0.0.0/0 без peer = «нет интернета».
                OlcrtcVpnService.suppressDestroyStop = true
                OlcrtcTunnelManager.stop(silent = true)
                runCatching {
                    startService(
                        Intent(this@SilentVpnService, OlcrtcVpnService::class.java).apply {
                            action = OlcrtcVpnService.ACTION_STOP
                        },
                    )
                }
                delay(200L)

                // 2) Ждём LTE/Wi‑Fi (prefer ≤3.5с, потом любой транспорт — самолётик/LTE).
                val preferTransport = pendingOlcrtcPreferTransport ?: preferFromReason
                WdttTunnelManager.logUi(
                    "net_wait",
                    "ждём готовность сети${preferTransport?.let { " ($it)" } ?: ""}…",
                    2,
                )
                val netOk = VpnNetworkHelper.awaitUnderlyingReady(
                    this@SilentVpnService,
                    timeoutMs = 18_000L,
                    preferTransport = preferTransport,
                    preferHoldMs = 3_500L,
                )
                if (!isRunning || epoch != disconnectEpoch) {
                    SessionTrace.mark("SilentVpnService.olcrtcRecover", "aborted — disconnected")
                    return@launch
                }
                if (!netOk) {
                    DebugLog.w("VpnService", "olcrtc recovery deferred — no underlying internet")
                    WdttTunnelManager.logUi(
                        "olcrtc_recover_wait",
                        "нет сети — интернет без VPN, ждём…",
                        2,
                    )
                    pausedForNetwork = true
                    isTunnelPaused = true
                    scheduleNetworkRecovery("internet_restored", 2_500L)
                    return@launch
                }

                // 3) Старт из кеша. На LTE nip.io fetch часто вешает recover — не делаем.
                val onMobile = VpnNetworkHelper.isOnMobileData(this@SilentVpnService)
                var cfgToUse = cfg!!
                if (OlcrtcRecoveryPolicy.shouldRefreshConfigOnRecover(onMobile, reason)) {
                    cfgToUse = withTimeoutOrNull(2_500L) {
                        refreshOlcrtcConfigJson(cfg, reason)
                    } ?: cfg
                    lastOlcrtcConfigJson = cfgToUse
                } else {
                    WdttTunnelManager.logUi("olcrtc_recover", "старт из кеша (без fetch)", 2)
                }

                OlcrtcTunnelManager.suppressPeerDeadFor(25_000L)
                lastTransportRestartMs = System.currentTimeMillis()
                startService(
                    Intent(this@SilentVpnService, OlcrtcVpnService::class.java).apply {
                        action = OlcrtcVpnService.ACTION_START
                        putExtra(OlcrtcVpnService.EXTRA_CONFIG, cfgToUse)
                    },
                )
                withContext(Dispatchers.Main) {
                    if (isRunning) {
                        startFg(buildConnectingNotification())
                        watchOlcrtcReadyNotification()
                        VpnTileHelper.requestUpdate(this@SilentVpnService)
                    }
                }
                // 4) Не висеть вечно в «переподключение».
                val ready = withTimeoutOrNull(55_000L) {
                    while (isActive && isRunning && epoch == disconnectEpoch) {
                        if (OlcrtcTunnelManager.tunnelReady.value) return@withTimeoutOrNull true
                        val err = OlcrtcTunnelManager.lastError.value
                        if (!err.isNullOrBlank() && !OlcrtcTunnelManager.running.value) {
                            return@withTimeoutOrNull false
                        }
                        delay(400L)
                    }
                    false
                } ?: false
                if (ready) {
                    pausedForNetwork = false
                    isTunnelPaused = false
                    WdttTunnelManager.logUi("olcrtc_recover_ok", "переподключение OK", 1)
                } else if (isRunning && epoch == disconnectEpoch) {
                    WdttTunnelManager.logUi(
                        "olcrtc_recover_fail",
                        "переподключение не поднялось — выкл/вкл VPN",
                        99,
                        isError = true,
                    )
                    if (OlcrtcRecoveryPolicy.shouldScheduleRecoverRetry(olcrtcEverReady, reason)) {
                        scheduleNetworkRecovery("$reason:retry", 4_000L)
                    }
                }
            } catch (e: CancellationException) {
                DebugLog.i("VpnService", "olcrtc recovery cancelled ($reason)")
                throw e
            } catch (e: Exception) {
                DebugLog.e("VpnService", "olcrtc recovery failed: ${e.message}", e)
                WdttTunnelManager.logUi(
                    "olcrtc_recover_fail",
                    "переподключение failed: ${e.message}",
                    99,
                    isError = true,
                )
            } finally {
                OlcrtcVpnService.suppressDestroyStop = false
                if (olcrtcRecoverGen.get() == myGen) {
                    olcrtcRecovering = false
                    pendingOlcrtcPreferTransport = null
                }
            }
        }
    }

    /** Ложные recovery (validated flip, idle verify) — не убивать libclient при живых воркерах. */
    private fun isRealNetworkRecoveryReason(reason: String): Boolean =
        NetworkRecoveryPolicy.isRealNetworkRecoveryReason(reason)

    private fun isSpuriousRecoveryReason(reason: String): Boolean =
        NetworkRecoveryPolicy.isSpuriousRecoveryReason(reason)

    private fun shouldSkipTransportRestart(reason: String): Boolean =
        NetworkRecoveryPolicy.shouldSkipTransportRestart(
            NetworkRecoveryPolicy.TransportRestartInput(
                bootstrapMode = WdttTunnelManager.isBootstrapMode(),
                reason = reason,
                transportHealthy = WdttTunnelManager.isTransportHealthy(),
                workerRampUpActive = WdttTunnelManager.isWorkerRampUpActive(),
                activeWorkers = WdttTunnelManager.activeWorkers.value,
                totalWorkers = WdttTunnelManager.lastParams()?.workers,
                lastTransportRestartMs = lastTransportRestartMs,
                nowMs = System.currentTimeMillis(),
                minRestartIntervalMs = MIN_TRANSPORT_RESTART_INTERVAL_MS,
            ),
        )

    private fun currentTrafficMb(): Double {
        val stats = WdttTunnelManager.stats.value
        return Regex("""Трафик:\s*([\d.]+)""")
            .find(stats)
            ?.groupValues
            ?.getOrNull(1)
            ?.toDoubleOrNull()
            ?: 0.0
    }

    private fun scheduleRecoveryVerification(reason: String, trafficBeforeMb: Double) {
        recoveryVerifyJob?.cancel()
        if (recoverySuppressedForRampUp()) return
        // fast-путь не трогал libclient — idle-трафик за 4 с не повод для полного restart.
        if (reason.startsWith("fast:") || reason.startsWith("resume:")) return
        // После transport_switch воркеры ramp-up 10–30 с — второй restart через 4 с не нужен.
        if (reason.contains("transport_switch")) return
        recoveryVerifyJob = scope.launch {
            delay(RECOVERY_VERIFY_DELAY_MS)
            if (!isRunning || phoneCallActive) return@launch
            if (WdttTunnelManager.isNetworkRecoverySuppressed()) return@launch
            if (WdttTunnelManager.isWorkerRampUpActive()) return@launch
            if (!VpnNetworkHelper.hasAnyUnderlyingInternet(this@SilentVpnService)) return@launch
            val workers = WdttTunnelManager.activeWorkers.value
            val trafficAfterMb = currentTrafficMb()
            val trafficDelta = trafficAfterMb - trafficBeforeMb
            if (workers <= 0 || trafficDelta < RECOVERY_MIN_TRAFFIC_DELTA_MB) {
                if (WdttTunnelManager.isTransportHealthy() && workers > 0) return@launch
                DebugLog.w(
                    "VpnService",
                    "recovery verify failed ($reason): workers=$workers delta=$trafficDelta MB; force restart",
                )
                lastTransportRestartMs = System.currentTimeMillis()
                WdttTunnelManager.restartTransportAfterNetwork()
                WdttTunnelManager.reapplyWireGuardForNetworkChange(applicationContext)
            }
        }
    }

    /** Пауза при полном обрыве; Wi‑Fi↔LTE → transport_switch (WDTT и olcrtc). */
    private fun checkUnderlyingNetwork() {
        val olcrtcLive =
            olcrtcSessionActive ||
                OlcrtcTunnelManager.running.value ||
                OlcrtcTunnelManager.tunnelReady.value
        val wdttLive = WdttTunnelManager.tunnelReady.value
        if (!isRunning || (!wdttLive && !olcrtcLive)) return
        if (!olcrtcLive && WdttTunnelManager.isNetworkRecoverySuppressed()) return
        if (NetworkRecoveryPolicy.shouldDeferRecoveryForPhoneCall(phoneCallActive)) return
        if (isOlcrtcInitialConnectInProgress()) {
            val anyOnline = VpnNetworkHelper.hasAnyUnderlyingInternet(this)
            val validatedOnline = VpnNetworkHelper.hasUnderlyingInternet(this)
            lastUnderlyingInternet = validatedOnline || anyOnline
            lastMobileDataState = VpnNetworkHelper.isOnMobileData(this)
            return
        }
        // transport_switch не блокируем grace — иначе первые секунды после connect «залипают».
        if (
            !olcrtcLive &&
            System.currentTimeMillis() - connectStartedAtMs < networkGraceMs()
        ) {
            return
        }

        val anyOnline = VpnNetworkHelper.hasAnyUnderlyingInternet(this)
        val validatedOnline = VpnNetworkHelper.hasUnderlyingInternet(this)
        val wasOnline = lastUnderlyingInternet
        val mobileNow = VpnNetworkHelper.isOnMobileData(this)
        val mobileWas = lastMobileDataState
        val underlyingFp = VpnNetworkHelper.underlyingTransportFingerprint(this)

        if (wasOnline == true && !anyOnline) {
            if (!pausedForNetwork) {
                DebugLog.i(
                    "VpnService",
                    "underlying internet lost — pause ${if (olcrtcLive) "olcrtc" else "libclient"}",
                )
                pausedForNetwork = true
                isTunnelPaused = true
                if (olcrtcLive) {
                    OlcrtcTunnelManager.stop(silent = true)
                } else {
                    WdttTunnelManager.pause()
                }
            }
        } else if ((wasOnline == false || pausedForNetwork) && (validatedOnline || anyOnline)) {
            scheduleNetworkRecovery("internet_restored", 1_500L)
        }
        // Синхронизируем fingerprint из poll (callback мог пропустить dual-network lost).
        if (underlyingFp.isNotEmpty() &&
            lastNetworkFingerprint.isNotEmpty() &&
            underlyingFp != lastNetworkFingerprint
        ) {
            val old = lastNetworkFingerprint
            val switch = wifiCellTransportTarget(old, underlyingFp)
            if (switch != null) {
                lastNetworkFingerprint = underlyingFp
                DebugLog.i("VpnService", "poll underlying $old → $underlyingFp → transport_switch:$switch")
                scheduleNetworkRecovery("transport_switch:$switch", 600L)
                lastMobileDataState = mobileNow
                lastUnderlyingInternet = validatedOnline || anyOnline
                return
            }
            lastNetworkFingerprint = underlyingFp
        } else if (underlyingFp.isNotEmpty() && lastNetworkFingerprint.isEmpty()) {
            lastNetworkFingerprint = underlyingFp
        }
        if (
            !WdttTunnelManager.isBootstrapMode() &&
            mobileWas != null &&
            mobileWas != mobileNow
        ) {
            // После Wi‑Fi off LTE часто ещё без VALIDATED — хватит anyOnline.
            if (validatedOnline || anyOnline) {
                val to = if (mobileNow) "mobile" else "wifi"
                DebugLog.i("VpnService", "network type switch detected -> $to; force recovery")
                scheduleNetworkRecovery("transport_switch:$to", 600L)
                lastMobileDataState = mobileNow
            }
            // Wi‑Fi выкл: LTE ещё не up — не обновляем lastMobileDataState, иначе switch пропустим.
        } else {
            lastMobileDataState = mobileNow
        }
        lastUnderlyingInternet = validatedOnline || (olcrtcLive && anyOnline)
    }

    private fun checkTransportHealth() {
        if (recoverySuppressedForRampUp()) {
            transportUnhealthySinceMs = 0L
            return
        }
        if (pausedForNetwork) return
        if (!isRunning || !WdttTunnelManager.tunnelReady.value || !WdttTunnelManager.running.value) {
            transportUnhealthySinceMs = 0L
            return
        }
        if (WdttTunnelManager.isNetworkRecoverySuppressed()) {
            transportUnhealthySinceMs = 0L
            return
        }
        if (System.currentTimeMillis() - connectStartedAtMs < networkGraceMs()) return
        val now = System.currentTimeMillis()
        if (!WdttTunnelManager.isTransportHealthy()) {
            if (transportUnhealthySinceMs == 0L) transportUnhealthySinceMs = now
            else if (now - transportUnhealthySinceMs >= TRANSPORT_UNHEALTHY_MS) {
                transportUnhealthySinceMs = 0L
                scheduleNetworkRecovery("unhealthy")
            }
        } else {
            transportUnhealthySinceMs = 0L
        }
        if (WdttTunnelManager.isTransportStale(TRANSPORT_STALE_MS)) {
            scheduleNetworkRecovery("stale")
        }
    }

    private fun setupPhoneCallMonitor() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        if (audioModeListener != null) return
        val am = getSystemService(AUDIO_SERVICE) as AudioManager
        audioManager = am
        val listener = AudioManager.OnModeChangedListener { mode ->
            if (!isRunning) return@OnModeChangedListener
            when (mode) {
                AudioManager.MODE_IN_CALL,
                AudioManager.MODE_IN_COMMUNICATION,
                AudioManager.MODE_RINGTONE,
                -> phoneCallActive = true
                AudioManager.MODE_NORMAL -> {
                    if (phoneCallActive) {
                        phoneCallActive = false
                        scheduleNetworkRecovery("phone_call_end", 3_000L)
                    }
                }
            }
        }
        audioModeListener = listener
        am.addOnModeChangedListener(mainExecutor, listener)
    }

    private fun teardownPhoneCallMonitor() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val listener = audioModeListener
            if (listener != null) {
                runCatching { audioManager?.removeOnModeChangedListener(listener) }
            }
        }
        audioModeListener = null
        audioManager = null
        phoneCallActive = false
    }

    private fun startTransportWatchdog() {
        transportWatchdogJob?.cancel()
        transportWatchdogJob = scope.launch {
            delay(1000)
            while (isActive && isRunning) {
                // olcrtc: watchdog своего транспорта; WDTT resume не трогаем.
                    if (
                        OlcrtcRecoveryPolicy.isOlcrtcSessionLive(
                            sessionActive = olcrtcSessionActive,
                            running = OlcrtcTunnelManager.running.value,
                            tunnelReady = OlcrtcTunnelManager.tunnelReady.value,
                            lastConfigPresent = lastOlcrtcConfigJson != null,
                        )
                    ) {
                    val action = OlcrtcRecoveryPolicy.decideWatchdog(
                        OlcrtcRecoveryPolicy.WatchdogInput(
                            sessionActive = olcrtcSessionActive,
                            running = OlcrtcTunnelManager.running.value,
                            tunnelReady = OlcrtcTunnelManager.tunnelReady.value,
                            recoverInFlight = isOlcrtcRecoverInFlight(),
                            initialConnectInProgress = isOlcrtcInitialConnectInProgress(),
                            starting = OlcrtcTunnelManager.isStarting(),
                            withinLibclientConnectGrace = isWithinConnectGrace(),
                            sinceRestartMs = System.currentTimeMillis() - lastTransportRestartMs,
                            socksHealthy = true, // probe only if SOCKS_DEAD candidate path
                        ),
                    )
                    // SOCKS probe дорогой — только когда остальные условия SOCKS_DEAD уже почти ок.
                    val resolved = if (
                        action == OlcrtcRecoveryPolicy.WatchdogAction.NONE &&
                        olcrtcSessionActive &&
                        OlcrtcTunnelManager.tunnelReady.value &&
                        !isOlcrtcRecoverInFlight() &&
                        !isOlcrtcInitialConnectInProgress() &&
                        !OlcrtcTunnelManager.isStarting() &&
                        !isWithinConnectGrace() &&
                        System.currentTimeMillis() - lastTransportRestartMs >
                            OlcrtcRecoveryPolicy.WATCHDOG_SOCKS_MS
                    ) {
                        val healthy = withContext(Dispatchers.IO) {
                            OlcrtcTunnelManager.probeSocksHealthy()
                        }
                        OlcrtcRecoveryPolicy.decideWatchdog(
                            OlcrtcRecoveryPolicy.WatchdogInput(
                                sessionActive = olcrtcSessionActive,
                                running = OlcrtcTunnelManager.running.value,
                                tunnelReady = OlcrtcTunnelManager.tunnelReady.value,
                                recoverInFlight = false,
                                initialConnectInProgress = false,
                                starting = false,
                                withinLibclientConnectGrace = false,
                                sinceRestartMs = System.currentTimeMillis() - lastTransportRestartMs,
                                socksHealthy = healthy,
                            ),
                        )
                    } else {
                        action
                    }
                    when (resolved) {
                        OlcrtcRecoveryPolicy.WatchdogAction.STUCK -> {
                            DebugLog.w("VpnService", "transportWatchdog: olcrtc stuck (running, not ready)")
                            scheduleNetworkRecovery("watchdog_olcrtc_stuck", 800L)
                        }
                        OlcrtcRecoveryPolicy.WatchdogAction.DOWN -> {
                            DebugLog.w("VpnService", "transportWatchdog: olcrtc down — recover")
                            scheduleNetworkRecovery("watchdog_olcrtc_down", 800L)
                        }
                        OlcrtcRecoveryPolicy.WatchdogAction.SOCKS_DEAD -> {
                            DebugLog.w("VpnService", "transportWatchdog: olcrtc SOCKS dead — recover")
                            scheduleNetworkRecovery("watchdog_olcrtc_socks", 500L)
                        }
                        OlcrtcRecoveryPolicy.WatchdogAction.NONE -> Unit
                    }
                    delay(2000)
                    continue
                }
                if (!WdttTunnelManager.running.value && !isTunnelPaused) {
                    if (isWithinConnectGrace()) {
                        delay(2000)
                        continue
                    }
                    if (WdttTunnelManager.tunnelReady.value) {
                        DebugLog.w("VpnService", "transportWatchdog: libclient down — restart")
                        scheduleNetworkRecovery("watchdog_down", 1_000L)
                    } else {
                        if (VpnNetworkHelper.hasAnyUnderlyingInternet(this@SilentVpnService)) {
                            DebugLog.w("VpnService", "transportWatchdog: libclient down before tunnel — resume")
                            WdttTunnelManager.resume()
                        } else {
                            DebugLog.i("VpnService", "transportWatchdog: waiting for internet restore")
                        }
                    }
                }
                delay(2000)
            }
        }
    }

    private fun teardownNetworkCallback() {
        networkCallback?.let { runCatching { connectivityManager?.unregisterNetworkCallback(it) } }
        networkCallback = null
    }

    /** Отключиться только если другой VPN реально захватил сеть (uid ≠ наш). */
    private fun setupVpnOwnershipMonitor() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        if (vpnOwnerCallback != null) return
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val ourUid = applicationInfo.uid
        vpnOwnerCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                if (!isRunning) return
                if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) return
                val owner = VpnNetworkHelper.vpnOwnerUid(cm, network)
                if (owner <= 0 || owner == ourUid) return
                DebugLog.w("VpnService", "Another VPN owns network (uid=$owner) — stopping Silent")
                disconnect()
            }
        }
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_VPN)
            .build()
        runCatching { cm.registerNetworkCallback(request, vpnOwnerCallback!!) }
    }

    private fun teardownVpnOwnershipMonitor() {
        vpnOwnerCallback?.let { cb ->
            runCatching {
                (getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager)
                    .unregisterNetworkCallback(cb)
            }
        }
        vpnOwnerCallback = null
    }

    private fun acquirePerformanceLocks() {
        performanceLocksHeld = true
        acquireWakeLock()
    }

    /** Держим partial wake lock на всё время VPN — иначе doze гасит libclient при выключенном экране. */
    private fun ensureSessionWakeLock() {
        if (!performanceLocksHeld) {
            performanceLocksHeld = true
        }
        acquireWakeLock()
    }

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "silent:tunnel_cpu").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    @Suppress("DEPRECATION")
    private fun acquireWifiLock() {
        if (wifiLock?.isHeld == true) return
        val wm = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        val mode = if (Build.VERSION.SDK_INT >= 29) {
            WifiManager.WIFI_MODE_FULL_LOW_LATENCY
        } else {
            WifiManager.WIFI_MODE_FULL_HIGH_PERF
        }
        wifiLock = wm.createWifiLock(mode, "silent:wifi_perf").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun releaseWakeLock() {
        if (wakeLock?.isHeld == true) wakeLock?.release()
        wakeLock = null
    }

    private fun releaseWifiLock() {
        if (wifiLock?.isHeld == true) wifiLock?.release()
        wifiLock = null
    }

    private fun startFg(notification: Notification) {
        try {
            when {
                Build.VERSION.SDK_INT >= 34 -> {
                    try {
                        startForeground(
                            NOTIF_ID,
                            notification,
                            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
                        )
                    } catch (e: Exception) {
                        DebugLog.w("VpnService", "FGS specialUse failed, fallback connectedDevice: ${e.message}")
                        startForeground(
                            NOTIF_ID,
                            notification,
                            ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE,
                        )
                    }
                }
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q -> {
                    startForeground(
                        NOTIF_ID,
                        notification,
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE,
                    )
                }
                else -> startForeground(NOTIF_ID, notification)
            }
        } catch (e: Exception) {
            SessionTrace.warn("SilentVpnService.startFg", e.message ?: "failed")
            DebugLog.e("VpnService", "startForeground failed", e)
            throw e
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java) ?: return
            val prefs = SilentPrefs.open(this)
            if (!prefs.getBoolean(PREF_NOTIF_CHANNELS_MIGRATED_V2, false)) {
                listOf("silent_vpn", "silent_vpn_status", "silent_vpn_fg").forEach { oldId ->
                    if (oldId != CHANNEL_ID) nm.deleteNotificationChannel(oldId)
                }
                prefs.edit().putBoolean(PREF_NOTIF_CHANNELS_MIGRATED_V2, true).apply()
            }
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Silent VPN",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = "Статус VPN и скорость"
                setShowBadge(false)
                enableVibration(false)
                setSound(null, null)
            }
            nm.createNotificationChannel(channel)
        }
    }

    private fun openAppIntent(): PendingIntent {
        val intent = MainActivity.openIntent(this)
        return PendingIntent.getActivity(
            this,
            NOTIF_OPEN_REQUEST_CODE,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun notificationTitle(ready: Boolean): String = when {
        ready -> "Silent VPN — подключено"
        else -> "Silent VPN — подключение…"
    }

    private fun notificationBody(ready: Boolean, stats: String): String {
        val trimmed = stats.trim()
        if (ready && trimmed.isNotBlank() && trimmed != "Ожидание данных…") return trimmed
        return when {
            ready -> "Туннель активен"
            else -> "Подключение к серверу…"
        }
    }

    /** FG-уведомление на время подключения. */
    private fun buildConnectingNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(BrandMarkIcons.iconCompat(this))
            .setContentTitle("Silent VPN — подключение…")
            .setContentText("Подключение к серверу…")
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .setSilent(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()

    private fun buildActiveNotification(stats: String): Notification {
        val body = notificationBody(ready = true, stats = stats)
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(BrandMarkIcons.iconCompat(this))
            .setContentTitle(notificationTitle(ready = true))
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()
    }

    private fun postVpnNotification(stats: String) {
        val tunnelUp =
            WdttTunnelManager.tunnelReady.value || OlcrtcTunnelManager.tunnelReady.value
        if (!isRunning || !tunnelUp) return
        val body = notificationBody(ready = true, stats = stats)
        val now = System.currentTimeMillis()
        if (body == lastNotifBody && now - lastNotifUpdateMs < NOTIF_UPDATE_MIN_MS) return
        if (now - lastNotifUpdateMs < NOTIF_UPDATE_MIN_MS && lastNotifBody.isNotBlank()) return
        lastNotifUpdateMs = now
        lastNotifBody = body
        startFg(buildActiveNotification(stats))
    }

    /** olcrtc: SilentVpnService держит FG, а ready приходит из OlcrtcTunnelManager. */
    private fun watchOlcrtcReadyNotification() {
        scope.launch {
            OlcrtcTunnelManager.tunnelReady.collect { ready ->
                if (!isRunning) return@collect
                if (ready) {
                    olcrtcEverReady = true
                    startFg(buildActiveNotification("olcrtc · туннель активен"))
                    VpnTileHelper.requestUpdate(this@SilentVpnService)
                } else if (OlcrtcTunnelManager.running.value) {
                    startFg(buildConnectingNotification())
                }
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        SessionTrace.mark("SilentVpnService.onTaskRemoved", "app swiped away running=$isRunning")
        if (isRunning) {
            // Не пишем vpn_session_active=true — при force-kill pref ломает reconnect по плитке.
            val stats = WdttTunnelManager.stats.value
            runCatching {
                if (WdttTunnelManager.tunnelReady.value) {
                    startFg(buildActiveNotification(stats))
                } else {
                    startFg(buildConnectingNotification())
                }
            }
        } else {
            VpnServiceTracker.markSessionActive(this, false)
        }
        VpnTileHelper.requestUpdate(this)
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        SessionTrace.enter("SilentVpnService.onDestroy")
        stopTunnelLocal(awaitStop = true, stopService = false)
        SessionTrace.exit("SilentVpnService.onDestroy")
        super.onDestroy()
    }

    /** Как stopTunnel() в reference TunnelService. */
    private fun stopTunnelLocal(awaitStop: Boolean = false, stopService: Boolean = true) {
        disconnectEpoch++
        disconnectJob?.cancel()
        transportWatchdogJob?.cancel()
        networkRecoveryJob?.cancel()
        recoveryVerifyJob?.cancel()
        statsUpdaterJob?.cancel()
        connectGuardJob?.cancel()
        isRunning = false
        isTunnelPaused = false
        activeNetworks.clear()
        lastNetworkFingerprint = ""
        transportUnhealthySinceMs = 0L
        lastMobileDataState = null
        lastTransportRestartMs = 0L
        VpnServiceTracker.markSessionActive(this, false)
        VpnBackendSync.stop()
        tunnelProxyStarted = false
        teardownNetworkCallback()
        teardownPhoneCallMonitor()
        teardownVpnOwnershipMonitor()
        performanceLocksHeld = false
        lastNotifBody = ""
        lastNotifUpdateMs = 0L
        SilentRepository.APP_EXCLUDED_FROM_VPN = true
        runCatching { VpnDataSyncScheduler.onMainVpnDisconnected(applicationContext) }
        dataSyncServiceStarted = false
        runCatching {
            if (awaitStop) {
                runBlocking { WdttTunnelManager.stopAndAwait() }
            } else {
                scope.launch { WdttTunnelManager.stopAndAwait() }
            }
        }
        releaseWakeLock()
        releaseWifiLock()
        clearVpnNotification()
        VpnTileHelper.requestUpdate(this)
        if (stopService) stopSelf()
    }

    private fun startConnectGuardIfNeeded() {
        connectGuardJob?.cancel()
        if (!connectFromTile) return
        connectGuardJob = scope.launch {
            delay(TILE_CONNECT_START_TIMEOUT_MS)
            if (!isRunning) return@launch
            if (WdttTunnelManager.tunnelReady.value || VpnSessionState.isActive()) return@launch
            val workers = WdttTunnelManager.activeWorkers.value
            if (workers > 0) return@launch
            SessionTrace.warn("SilentVpnService.CONNECT", "tile timeout no tunnel/workers")
            DebugLog.w("VpnService", "tile connect timeout — reset stale startup")
            runCatching {
                VpnConnectHelper.ensureCleanSlate(this@SilentVpnService, force = true)
            }.onFailure { e ->
                DebugLog.w("VpnService", "tile timeout cleanSlate: ${e.message}")
            }
            isRunning = false
            VpnServiceTracker.markSessionActive(this@SilentVpnService, false)
            clearVpnNotification()
            VpnTileHelper.requestUpdate(this@SilentVpnService)
            stopSelf()
        }
    }

    private fun loadSavedServerHashes(): List<String> {
        val json = SilentPrefs.open(this)
            .getString(SilentRepository.PREF_SAVED_HASH_ITEMS, null) ?: return emptyList()
        val items = runCatching {
            val type = object : TypeToken<List<HashItemDto>>() {}.type
            Gson().fromJson<List<HashItemDto>>(json, type)
        }.getOrDefault(emptyList())
        return HashParser.normalizeList(
            items.filter {
                it.source != "bootstrap" && it.is_active && it.status == "active" && it.hash.isNotBlank()
            }.map { it.hash.trim() },
        ).filter { it.isNotBlank() }.distinct().take(HashChannelHelper.MAX_HASHES)
    }

    private fun loadSavedActiveServerHashCount(): Int = loadSavedServerHashes().size

    private fun repoResolveTotalWorkers(activeHashCount: Int): Int {
        val activeHashes = activeHashCount.coerceIn(1, HashChannelHelper.MAX_HASHES)
        if (!BuildConfig.DEBUG) {
            return HashChannelHelper.workersForLibclient(
                HashChannelHelper.normalizeTotalWorkers(HashChannelHelper.DEFAULT_TOTAL_WORKERS, activeHashes),
                activeHashes,
            )
        }
        val prefs = SilentPrefs.open(this)
        val max = HashChannelHelper.maxTotalWorkers(activeHashes)
        val saved = when {
            prefs.contains(SilentRepository.PREF_HASH_TOTAL_WORKERS) -> {
                val raw = prefs.getInt(
                    SilentRepository.PREF_HASH_TOTAL_WORKERS,
                    HashChannelHelper.WORKERS_PER_GROUP,
                )
                if (raw > max) max else HashChannelHelper.normalizeTotalWorkers(raw, activeHashes)
            }
            prefs.contains(SilentRepository.PREF_HASH_CHANNELS_PER_HASH) &&
                !prefs.getBoolean(SilentRepository.PREF_HASH_LEGACY_MIGRATED, false) -> {
                HashChannelHelper.migrateLegacyPerHash(
                    prefs.getInt(
                        SilentRepository.PREF_HASH_CHANNELS_PER_HASH,
                        HashChannelHelper.WORKERS_PER_GROUP,
                    ),
                    activeHashes,
                )
            }
            else -> HashChannelHelper.normalizeTotalWorkers(
                HashChannelHelper.DEFAULT_TOTAL_WORKERS,
                activeHashes,
            )
        }
        return HashChannelHelper.workersForLibclient(saved, activeHashes)
    }
}
