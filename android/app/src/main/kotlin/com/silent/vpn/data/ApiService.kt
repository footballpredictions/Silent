package com.silent.vpn.data

import retrofit2.Response
import retrofit2.http.*

// ─── DTOs ────────────────────────────────────────────────────────────────────

data class LoginRequest(val email: String, val password: String)
data class RegisterRequest(val email: String, val password: String)
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
)

data class DeviceRegisterRequest(
    val device_name: String,
    val device_type: String,
    val device_fingerprint: String,
    val wg_public_key: String?,
)

data class BootstrapConfigRequest(
    val bootstrap_hash: String,
    val device_type: String,
    val device_fingerprint: String,
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
)

data class ConnectRequest(val device_fingerprint: String, val device_type: String, val last_ip: String? = null)
data class DisconnectRequest(val device_fingerprint: String)

data class ThemeData(
    val primary_color: String = "#000000",
    val background_color: String = "#FFFFFF",
    val text_color: String = "#000000",
    val accent_color: String = "#1A1A1A",
    val toggle_on_color: String = "#000000",
    val toggle_off_color: String = "#CCCCCC",
    val font_family: String = "Inter",
    val logo_url: String = "",
    val app_name: String = "Silent",
    val support_url: String = "",
    val privacy_url: String = "",
    val terms_url: String = "",
)

data class PaymentInitRequest(val plan_type: String, val promo_code: String? = null)
data class PaymentResponse(val url: String, val wallet: String, val label: String, val amount: Double)

data class PromoCheckRequest(val code: String, val plan_type: String)
data class PromoCheckResponse(
    val code: String,
    val discount_percent: Int,
    val extra_days: Int,
    val original_price: Double,
    val discounted_price: Double,
)

// ─── API Interface ────────────────────────────────────────────────────────────

interface SilentApi {
    @POST("api/auth/login")
    suspend fun login(@Body req: LoginRequest): Response<TokenResponse>

    @POST("api/auth/register")
    suspend fun register(@Body req: RegisterRequest): Response<Map<String, String>>

    @POST("api/auth/refresh")
    suspend fun refresh(@Body req: RefreshRequest): Response<TokenResponse>

    @GET("api/users/me")
    suspend fun getProfile(): Response<UserProfile>

    @POST("api/users/logout")
    suspend fun logoutSession(@Body req: DisconnectRequest): Response<Map<String, String>>

    @GET("api/vpn/theme")
    suspend fun getTheme(): Response<ThemeData>

    @POST("api/vpn/device/register")
    suspend fun registerDevice(@Body req: DeviceRegisterRequest): Response<VpnConfig>

    @GET("api/vpn/config")
    suspend fun getConfig(@Query("fingerprint") fingerprint: String): Response<VpnConfig>

    @POST("api/vpn/connect")
    suspend fun connect(@Body req: ConnectRequest): Response<Map<String, String>>

    @POST("api/vpn/disconnect")
    suspend fun disconnect(@Body req: DisconnectRequest): Response<Map<String, String>>

    @POST("api/payments/init")
    suspend fun initPayment(@Body req: PaymentInitRequest): Response<PaymentResponse>

    @POST("api/payments/promo/check")
    suspend fun checkPromo(@Body req: PromoCheckRequest): Response<PromoCheckResponse>

    @GET("api/payments/plans")
    suspend fun getPlans(): Response<List<Map<String, Any>>>

    @POST("api/auth/vk/guest/link/start")
    suspend fun vkGuestLinkStart(): Response<VkGuestLinkStartResponse>

    @GET("api/auth/vk/guest/status")
    suspend fun vkGuestStatus(@Query("state") state: String): Response<VkGuestStatusResponse>

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

    @POST("api/vpn/bootstrap-config")
    suspend fun bootstrapConfig(@Body req: BootstrapConfigRequest): Response<VpnConfig>
}
