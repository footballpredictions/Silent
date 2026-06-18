package com.silent.vpn.auth

import androidx.activity.ComponentActivity
import androidx.credentials.CreatePasswordRequest
import androidx.credentials.CredentialManager
import androidx.credentials.exceptions.CreateCredentialException

object CredentialHelper {
    /** Предложить Google / менеджеру паролей сохранить учётные данные после успешного входа. */
    suspend fun offerSavePassword(activity: ComponentActivity, email: String, password: String) {
        if (email.isBlank() || password.isBlank()) return
        try {
            val cm = CredentialManager.create(activity)
            val request = CreatePasswordRequest(
                id = email.trim(),
                password = password,
            )
            cm.createCredential(activity, request)
        } catch (_: CreateCredentialException) {
        } catch (_: Exception) {
        }
    }
}
