package com.silent.vpn.data

data class VkGuestCompleteRequest(
    val state: String,
    val access_token: String,
    val vk_user_id: Long,
    val bootstrap_hash: String,
)
