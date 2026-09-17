package com.silent.vpn.policy

/**
 * Админка «Доп. настройки» → отключение подтверждения почты.
 * Поле в register — строка ("true"/"false"), чтобы Gson Map<String,String> не падал.
 */
object EmailConfirmationPolicy {

    fun skipConfirmation(themeSkip: Boolean, requiredFlag: String?): Boolean {
        if (themeSkip) return true
        return requiredFlag.equals("false", ignoreCase = true)
    }
}
