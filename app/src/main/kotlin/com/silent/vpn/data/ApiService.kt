package com.silent.vpn.data

import retrofit2.Response
import retrofit2.http.*

// ─── DTOs ────────────────────────────────────────────────────────────────────

data class LoginDeviceInfo(
    val device_fingerprint: String,
    val device_type: String = "android",
    val device_name: String = "Android",
)

data class LoginRequest(
    val email: String,
    val password: String,
    val device: LoginDeviceInfo? = null,
)
data class RegisterRequest(
    val email: String,
    val password: String,
    val referral_or_promo: String? = null,
)
data class ForgotPasswordRequest(val email: String)
data class TokenResponse(val access_token: String, val refresh_token: String)
data class RefreshRequest(val refresh_token: String)

data class SubscriptionInfo(
    val is_active: Boolean,
    val plan_type: String?,
    val expires_at: String?,
    val days_left: Int = 0,
)

data class DeviceInfo(
    val id: String,
    val device_name: String,
    val device_type: String,
    val device_fingerprint: String? = null,
    val is_connected: Boolean,
    val last_connected: String?,
)

data class UserProfile(
    val id: String,
    val email: String,
    val display_id: String,
    val is_admin: Boolean = false,
    val subscription: SubscriptionInfo,
    val devices: List<DeviceInfo>,
    val devices_count: Int,
    val connected_count: Int = 0,
    val max_devices: Int,
    val vk_linked: Boolean = false,
    val vk_user_id: Long? = null,
)

/** 0 или is_admin = безлимит слотов. */
fun UserProfile.deviceLimitLabel(): String =
    if (is_admin || max_devices <= 0) "∞" else max_devices.toString()

fun UserProfile.sessionsBadge(): String = "${devices_count}/${deviceLimitLabel()}"

data class VkGuestLinkStartResponse(val auth_url: String, val state: String)

data class VkGuestStatusResponse(
    val completed: Boolean = false,
    val vk_user_id: Long? = null,
    val bootstrap_hash: String? = null,
)

data class VkAttachRequest(val vk_user_id: Long)

data class VkAttachResponse(
    val linked: Boolean = false,
    val vk_user_id: Long? = null,
    val bootstrap_hash: String? = null,
    val hashes: List<String>? = null,
)

data class VkLinkStartResponse(val auth_url: String, val bot_url: String = "")
data class VkLinkStatusResponse(
    val linked: Boolean,
    val vk_user_id: Long? = null,
    val bot_url: String = "",
    val bootstrap_hash: String? = null,
)

data class VpnHashesResponse(
    val hashes: List<String>,
    val bootstrap_hash: String? = null,
    val mode: String? = null,
    val items: List<HashItemDto>? = null,
)

data class HashItemDto(
    val hash: String,
    val label: String,
    val source: String,
    val slot_index: Int? = null,
    val is_active: Boolean = true,
    val status: String = "active",
)

data class HashFailureReportRequest(
    val hash: String,
    val error_type: String,
    val message: String = "",
    val device_fingerprint: String,
)

/**
 * Репорт агенту доступности: на какой стадии сорвалось подключение.
 * `age_sec` — сколько репорт пролежал в очереди, чтобы сервер отнёс отказ
 * к моменту самого сбоя, а не к моменту доставки.
 */
data class ReachabilityReportRequest(
    val stage: String,
    val transport: String = "",
    val network_type: String = "",
    val carrier: String = "",
    val server_slot: String = "",
    val tunnel_uptime_sec: Int? = null,
    val platform: String = "android",
    val app_version: String = "",
    val detail: String = "",
    val age_sec: Int? = null,
)

data class DeviceRenameRequest(val device_name: String)

data class DeviceRegisterRequest(
    val device_name: String,
    val device_type: String,
    val device_fingerprint: String,
    val wg_public_key: String?,
    val bootstrap_hash: String? = null,
    val preferred_server: String? = null,
)

data class BootstrapConfigRequest(
    val bootstrap_hash: String,
    val device_type: String,
    val device_fingerprint: String,
)

data class ClientSyncBundle(
    val profile: UserProfile? = null,
    val theme: ThemeData? = null,
    val referral: ReferralInfo? = null,
    val hashes: List<String>? = null,
    val sync: SyncStateResponse? = null,
)

data class VpnConfig(
    val device_id: String,
    val wg_private_key: String,
    val wg_address: String,
    val wg_dns: String,
    val server_ip: String,
    val server_port: Int,
    val server_public_key: String,
    val wdtt_password: String,
    val vk_hashes: List<String>,
    val stream_count: Int,
    val selected_server: String? = null,
    val client_sync: ClientSyncBundle? = null,
)

data class ConnectRequest(
    val device_fingerprint: String,
    val device_type: String,
    val last_ip: String? = null,
    val preferred_server: String? = null,
)

data class PreferredServerRequest(
    val device_fingerprint: String,
    val preferred_server: String,
)

data class VpnServerInfo(
    val key: String,
    val title: String,
    val public_ip: String,
    val wdtt_port: Int,
    val online_count: Int = 0,
    val api_base: String = "",
)

data class VpnServersResponse(
    val selected_server: String? = null,
    val servers: List<VpnServerInfo> = emptyList(),
)
data class DisconnectRequest(val device_fingerprint: String)

data class OlcrtcProviderPublic(
    val enabled: Boolean = false,
    val room: String = "",
    val transport: String = "datachannel",
    val room_slot_id: String = "",
    val room_db_id: String = "",
    val rooms_count: Int = 0,
    val denied: Boolean = false,
    /** WB Stream account JWT — без него guest getToken → 403 */
    val auth_token: String = "",
)

data class OlcrtcPublicConfig(
    val enabled: Boolean = false,
    val crypto_key: String = "",
    val socks_host: String = "127.0.0.1",
    val socks_port: Int = 8808,
    val assigned_slot: String = "",
    val device_type: String = "",
    val jitsi_https_proxy: String = "",
    val pool_denied: Boolean = false,
    val pool_denied_detail: String = "",
    val providers: Map<String, OlcrtcProviderPublic> = emptyMap(),
)

data class OlcrtcHeartbeatRequest(
    val room_db_id: String = "",
    val fingerprint: String = "",
    val provider: String = "",
    val device_type: String = "android",
    val online: Boolean = true,
)

data class OlcrtcRoomFailureRequest(
    val room_db_id: String = "",
    val fingerprint: String = "",
    val provider: String = "",
    val device_type: String = "android",
    val detail: String = "",
)

data class ThemeData(
    val primary_color: String = "#000000",
    val background_color: String = "#FFFFFF",
    val text_color: String = "#000000",
    val accent_color: String = "#1A1A1A",
    val toggle_on_color: String = "#000000",
    val toggle_off_color: String = "#CCCCCC",
    val font_family: String = "Inter",
    val logo_url: String = "",
    val home_bg_image_url: String = "",
    val app_name: String = "Silent VPN",
    val support_url: String = "https://t.me/silentvpn3?direct",
    val telegram_channel_url: String = "https://t.me/silentvpn3",
    val telegram_proxy_url: String = "",
    val telegram_proxy_menu_label: String = "Ускорить Telegram",
    val privacy_url: String = "",
    val terms_url: String = "",
    val update_bar_background_color: String = "#2563EB",
    val update_bar_text_color: String = "#FFFFFF",
    val update_bar_progress_color: String = "#1D4ED8",
    val update_bar_label_available: String = "Доступно обновление",
    val update_bar_label_downloading: String = "Скачивание…",
    val dark_primary_color: String = "",
    val dark_background_color: String = "",
    val dark_text_color: String = "",
    val dark_accent_color: String = "",
    val dark_toggle_on_color: String = "",
    val dark_toggle_off_color: String = "",
    val dark_update_bar_background_color: String = "",
    val dark_update_bar_text_color: String = "",
    val dark_update_bar_progress_color: String = "",
    val dark_login_link_color: String = "",
    val login_step1_title: String = "Шаг 1 — хеш звонка VK",
    val login_step1_instruction: String = "Скопируйте хеш из раздела «Звонки» в приложении ВКонтакте (на ПК — VK Звонки в браузере). Вставьте хеш или ссылку ниже — временный канал только для входа или регистрации (2 мин).",
    val login_hash_placeholder: String = "Хеш или ссылка на звонок VK",
    val login_hash_button_text: String = "Подтвердить",
    val login_vk_mobile_url: String = "https://vk.com/calls",
    val login_vk_mobile_link_text: String = "ВКонтакте — раздел «Звонки»",
    val login_vk_pc_url: String = "https://vk.com/calls",
    val login_vk_pc_link_text: String = "VK Звонки в браузере",
    val login_link_color: String = "#4680C2",
    val login_step2_title: String = "Шаг 2 — вход или регистрация",
    val login_remember_me_label: String = "Запомнить меня",
    val login_forgot_password_label: String = "Забыли пароль?",
    val login_forgot_title: String = "Восстановление пароля",
    val login_forgot_instruction: String = "Введите email — мы отправим ссылку для установки нового пароля.",
    val login_reset_title: String = "Новый пароль",
    val login_reset_button_text: String = "Сохранить пароль",
    val hive_standby_api_urls: String = "",
    val menu_bonuses_label: String = "Бонусы",
    val bonuses_title: String = "Бонусы",
    val bonuses_intro_text: String = "",
    val bonuses_referral_title: String = "Ваша ссылка",
    val bonuses_referral_hint: String = "Скопируйте и отправьте другу",
    val bonuses_promo_title: String = "Промокод",
    val bonuses_promo_hint: String = "Проверить скидку к тарифу",
    val bonuses_rules_text: String = "",
    val bonuses_copy_link_label: String = "Копировать ссылку",
    val bonuses_copy_code_label: String = "Копировать код",
    val register_referral_or_promo_label: String = "Промокод или реферальный код",
    val register_referral_or_promo_hint: String = "Необязательно. Введите промокод или код из реферальной ссылки.",
    val payment_waiting_title: String = "Ждём подтверждения оплаты",
    val payment_waiting_text: String = "Оплатите в открывшейся вкладке браузера. После оплаты вернитесь в приложение — подписка активируется автоматически, обычно в течение минуты.",
    val payment_success_title: String = "Оплата прошла успешно",
    val payment_success_text: String = "Подписка активирована. Спасибо за покупку!",
    val payment_failed_title: String = "Оплата не прошла",
    val payment_failed_text: String = "Платёж не был подтверждён. Попробуйте снова или обратитесь в поддержку.",
    val payment_timeout_title: String = "Не дождались оплаты",
    val payment_timeout_text: String = "Если вы уже оплатили — подождите ещё немного или проверьте позже в разделе «Подписка».",
    val payment_retry_button_text: String = "Попробовать снова",
    val payment_cancel_button_text: String = "Отмена",
)

data class PaymentInitRequest(val plan_type: String, val promo_code: String? = null)
data class PaymentResponse(val url: String, val wallet: String, val label: String, val amount: Double)
data class PaymentStatusResponse(val label: String, val status: String, val plan_type: String, val amount: Double)

data class PromoCheckRequest(val code: String, val plan_type: String)
data class PromoCheckResponse(
    val code: String,
    val discount_percent: Int,
    val extra_days: Int,
    val original_price: Double,
    val discounted_price: Double,
)

data class ReferralInfo(
    val referral_code: String,
    val referral_link: String,
    val invited_count: Int = 0,
    val rewarded_count: Int = 0,
    val pending_count: Int = 0,
    val bonus_days: Int = 30,
)

data class UpdateCheckResponse(
    val available: Boolean = false,
    val version: String? = null,
    val filename: String? = null,
    val size: Long = 0,
    val uploaded_at: String? = null,
    val download_url: String? = null,
    val github_download_url: String? = null,
    val tunnel_download_url: String? = null,
)

data class SyncStateResponse(
    val revision: Long = 0,
    val hashes: Long = 0,
    val theme: Long = 0,
    val profile: Long = 0,
    val changed: List<String> = emptyList(),
)

// ─── API Interface ────────────────────────────────────────────────────────────

interface SilentApi {
    @POST("api/auth/login")
    suspend fun login(@Body req: LoginRequest): Response<TokenResponse>

    @POST("api/auth/register")
    suspend fun register(@Body req: RegisterRequest): Response<Map<String, String>>

    @POST("api/auth/forgot-password")
    suspend fun forgotPassword(@Body req: ForgotPasswordRequest): Response<Map<String, String>>

    @POST("api/auth/refresh")
    suspend fun refresh(@Body req: RefreshRequest): Response<TokenResponse>

    @GET("api/users/me")
    suspend fun getProfile(): Response<UserProfile>

    @GET("api/users/me/referral")
    suspend fun getReferral(): Response<ReferralInfo>

    @PATCH("api/users/devices/{deviceId}")
    suspend fun renameDevice(
        @Path("deviceId") deviceId: String,
        @Body req: DeviceRenameRequest,
    ): Response<Map<String, String>>

    @DELETE("api/users/devices/{deviceId}")
    suspend fun deleteDevice(@Path("deviceId") deviceId: String): Response<Map<String, String>>

    @POST("api/users/logout")
    suspend fun logoutSession(@Body req: DisconnectRequest): Response<Map<String, String>>

    @GET("api/vpn/theme")
    suspend fun getTheme(): Response<ThemeData>

    @GET("api/vpn/olcrtc2-config")
    suspend fun getOlcrtcConfig(
        @Query("device_type") deviceType: String,
        @Query("fingerprint") fingerprint: String,
        @Query("provider") provider: String = "",
    ): Response<OlcrtcPublicConfig>

    @POST("api/vpn/olcrtc2-heartbeat")
    suspend fun olcrtcHeartbeat(@Body req: OlcrtcHeartbeatRequest): Response<Map<String, Any>>

    @POST("api/vpn/olcrtc2-room-failure")
    suspend fun olcrtcRoomFailure(@Body req: OlcrtcRoomFailureRequest): Response<Map<String, Any>>

    @POST("api/vpn/device/register")
    suspend fun registerDevice(@Body req: DeviceRegisterRequest): Response<VpnConfig>

    @GET("api/vpn/config")
    suspend fun getConfig(
        @Query("fingerprint") fingerprint: String,
        @Query("preferred_server") preferredServer: String? = null,
    ): Response<VpnConfig>

    @POST("api/vpn/connect")
    suspend fun connect(@Body req: ConnectRequest): Response<Map<String, String>>

    @GET("api/vpn/servers")
    suspend fun getVpnServers(@Query("fingerprint") fingerprint: String): Response<VpnServersResponse>

    @POST("api/vpn/servers/select")
    suspend fun selectVpnServer(@Body req: PreferredServerRequest): Response<VpnServersResponse>

    @POST("api/vpn/disconnect")
    suspend fun disconnect(@Body req: DisconnectRequest): Response<Map<String, String>>

    @POST("api/payments/init")
    suspend fun initPayment(@Body req: PaymentInitRequest): Response<PaymentResponse>

    @GET("api/payments/status/{label}")
    suspend fun getPaymentStatus(@Path("label") label: String): Response<PaymentStatusResponse>

    @POST("api/payments/promo/check")
    suspend fun checkPromo(@Body req: PromoCheckRequest): Response<PromoCheckResponse>

    @GET("api/payments/plans")
    suspend fun getPlans(): Response<List<Map<String, Any>>>

    @POST("api/auth/vk/guest/link/start")
    suspend fun vkGuestLinkStart(): Response<VkGuestLinkStartResponse>

    @GET("api/auth/vk/guest/status")
    suspend fun vkGuestStatus(@Query("state") state: String): Response<VkGuestStatusResponse>

    @POST("api/auth/vk/guest/complete")
    suspend fun vkGuestComplete(@Body req: VkGuestCompleteRequest): Response<Map<String, Any>>

    @POST("api/auth/vk/link/attach")
    suspend fun vkLinkAttach(@Body req: VkAttachRequest): Response<VkAttachResponse>

    @POST("api/auth/vk/link/start")
    suspend fun vkLinkStart(): Response<VkLinkStartResponse>

    @GET("api/auth/vk/status")
    suspend fun vkLinkStatus(): Response<VkLinkStatusResponse>

    @GET("api/auth/vk/config-sync")
    suspend fun vkConfigSync(): Response<VpnConfig>

    @GET("api/auth/vk/bootstrap-hash")
    suspend fun vkBootstrapHash(): Response<VpnHashesResponse>

    @GET("api/vpn/hashes")
    suspend fun getVpnHashes(): Response<VpnHashesResponse>

    @GET("api/vpn/sync-state")
    suspend fun getSyncState(
        @Query("hashes_since") hashesSince: Long = 0,
        @Query("theme_since") themeSince: Long = 0,
        @Query("profile_since") profileSince: Long = 0,
    ): Response<SyncStateResponse>

    @POST("api/vpn/hashes/request-refresh")
    suspend fun requestHashRefresh(@Body req: ConnectRequest): Response<VpnHashesResponse>

    @POST("api/vpn/hashes/report-failure")
    suspend fun reportHashFailure(@Body req: HashFailureReportRequest): Response<Map<String, String>>

    @POST("api/vpn/reachability-report")
    suspend fun reportReachability(@Body req: ReachabilityReportRequest): Response<Map<String, Any>>

    @POST("api/vpn/bootstrap-config")
    suspend fun bootstrapConfig(@Body req: BootstrapConfigRequest): Response<VpnConfig>

    @GET("api/updates/check")
    suspend fun checkUpdate(
        @Query("platform") platform: String,
        @Query("version") version: String,
    ): Response<UpdateCheckResponse>
}
