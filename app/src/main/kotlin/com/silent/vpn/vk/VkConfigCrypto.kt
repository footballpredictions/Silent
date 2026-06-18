package com.silent.vpn.vk

import com.google.gson.Gson
import com.silent.vpn.data.VpnConfig
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import android.util.Base64

object VkConfigCrypto {
    private const val PREFIX = "SILENT:v1:"
    private const val PEPPER = "silent_vpn_config_v1"
    private const val APP_ID = 54610377L

    private fun deriveKey(vkUserId: Long): ByteArray {
        val raw = "$vkUserId:$APP_ID:$PEPPER".toByteArray()
        return MessageDigest.getInstance("SHA-256").digest(raw)
    }

    fun extractConfigBlob(text: String): String? {
        val idx = text.indexOf(PREFIX)
        if (idx < 0) return null
        val rest = text.substring(idx)
        val end = rest.indexOfFirst { it.isWhitespace() }
        return if (end < 0) rest.trim() else rest.substring(0, end).trim()
    }

    fun decryptFromText(vkUserId: Long, text: String): VpnConfig? {
        val blob = extractConfigBlob(text) ?: return null
        return decryptMessage(vkUserId, blob)
    }

    fun decryptMessage(vkUserId: Long, message: String): VpnConfig? {
        if (!message.startsWith(PREFIX)) return null
        val blob = message.removePrefix(PREFIX)
        return try {
            val padded = blob + "=".repeat((4 - blob.length % 4) % 4)
            val raw = Base64.decode(padded, Base64.URL_SAFE)
            val nonce = raw.copyOfRange(0, 12)
            val ciphertext = raw.copyOfRange(12, raw.size)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            val key = SecretKeySpec(deriveKey(vkUserId), "AES")
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, nonce))
            val json = String(cipher.doFinal(ciphertext))
            val map = Gson().fromJson(json, Map::class.java)
            val hashes = (map["vk_hashes"] as? List<*>)?.mapNotNull { it as? String } ?: emptyList()
            VpnConfig(
                device_id = map["device_id"]?.toString() ?: "",
                wg_private_key = map["wg_private_key"]?.toString() ?: "",
                wg_address = map["wg_address"]?.toString() ?: "",
                wg_dns = map["wg_dns"]?.toString() ?: "77.88.8.8,77.88.8.1",
                server_ip = map["server_ip"]?.toString() ?: "",
                server_port = (map["server_port"] as? Double)?.toInt() ?: (map["server_port"] as? Int) ?: 56000,
                server_public_key = map["server_public_key"]?.toString() ?: "",
                wdtt_password = map["wdtt_password"]?.toString() ?: "",
                vk_hashes = hashes,
                stream_count = (map["stream_count"] as? Double)?.toInt() ?: 3,
            )
        } catch (_: Exception) {
            null
        }
    }
}
