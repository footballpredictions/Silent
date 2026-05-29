package com.silent.vpn.data

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Единое хранилище настроек (encrypted + fallback), как в [Repository]. */
object SilentPrefs {
    private const val TAG = "SilentPrefs"
    private const val NAME = "silent_prefs"

    fun open(context: Context): SharedPreferences {
        return try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context, NAME, masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        } catch (e: Exception) {
            Log.w(TAG, "EncryptedSharedPreferences unavailable, using regular prefs", e)
            context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
        }
    }
}
