package com.silent.vpn.policy

import com.silent.vpn.data.PaymentPreview
import java.util.Locale

object PromotionalPrice {
    fun label(fallback: String, preview: PaymentPreview?, nowMillis: Long = System.currentTimeMillis()): String {
        if (preview == null || preview.promo_code.isNullOrBlank() || !preview.isFresh(nowMillis) ||
            !preview.amount.isFinite() || preview.amount < 0) return fallback
        return if (preview.amount == preview.amount.toLong().toDouble()) "${preview.amount.toLong()} ₽"
        else String.format(Locale.forLanguageTag("ru-RU"), "%.2f ₽", preview.amount)
    }
}
