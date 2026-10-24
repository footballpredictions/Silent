package com.silent.vpn.policy

import com.silent.vpn.data.PaymentPreview
import org.junit.Assert.assertEquals
import org.junit.Test

class PromotionalPriceTest {
    private val now = 1792843200000L
    private val quote = PaymentPreview(139.3, "2026-11-24T12:00:00Z", "", "2026-10-24T12:00:00Z", "ЧЕЧИЛ")

    @Test fun onlyPersonalPromoQuoteChangesPrice() {
        assertEquals("139,30 ₽", PromotionalPrice.label("199 ₽", quote, now))
        assertEquals("199 ₽", PromotionalPrice.label("199 ₽", null, now))
        assertEquals("199 ₽", PromotionalPrice.label("199 ₽", quote.copy(promo_code = null), now))
        assertEquals("199 ₽", PromotionalPrice.label("199 ₽", quote.copy(promo_code = " "), now))
    }

    @Test fun invalidOrExpiredQuoteFallsBackToBase() {
        for (invalid in listOf(quote.copy(amount = -1.0), quote.copy(amount = Double.NaN),
            quote.copy(amount = Double.POSITIVE_INFINITY), quote.copy(calculated_at = null),
            quote.copy(calculated_at = "invalid"), quote.copy(calculated_at = "2026-10-24T12:01:00Z"))) {
            assertEquals("199 ₽", PromotionalPrice.label("199 ₽", invalid, now))
        }
        assertEquals("199 ₽", PromotionalPrice.label("199 ₽", quote, now + 300001))
    }

    @Test fun noClientSidePercentageCalculationOrRoundingToWholeRubles() {
        for ((amount, label) in listOf(139.3 to "139,30 ₽", 251.3 to "251,30 ₽", 334.6 to "334,60 ₽",
            1049.3 to "1049,30 ₽", 231.0 to "231 ₽", 415.8 to "415,80 ₽", 554.4 to "554,40 ₽", 0.0 to "0 ₽")) {
            assertEquals(label, PromotionalPrice.label("base", quote.copy(amount = amount), now))
        }
    }
}
