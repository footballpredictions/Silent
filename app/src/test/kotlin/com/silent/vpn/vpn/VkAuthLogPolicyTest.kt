package com.silent.vpn.vpn

import org.junit.Assert.*
import org.junit.Test

class VkAuthLogPolicyTest {
    @Test fun `logged internal error is temporary and cannot force legacy restart`() {
        val line = "[VK Auth] LEGACY_ESCALATE_CAPTCHA step=step3 kind=vk_api: error_code=10 Internal server error"
        assertTrue(VkAuthLogPolicy.isTemporaryApiFailure(line))
        assertFalse(VkAuthLogPolicy.shouldEscalateFromLog(line))
        assertTrue(VkAuthLogPolicy.isTemporaryApiFailure("error_code=10 Unknown error, try later"))
        assertFalse(VkAuthLogPolicy.isTemporaryApiFailure("error_code=100 token expired"))
        assertFalse(VkAuthLogPolicy.isTemporaryApiFailure("call not found (error_code=10)"))
    }

    @Test fun `real captcha and flood still reach the existing host policy`() {
        assertTrue(VkAuthLogPolicy.shouldEscalateFromLog("LEGACY_ESCALATE_CAPTCHA error_code=14 captcha needed"))
        assertTrue(VkAuthLogPolicy.shouldEscalateFromLog("kind=flood error_code=9 Flood control"))
    }

    @Test fun `native prefix resolves only to a complete known hash`() {
        val prefix = VkAuthLogPolicy.cleanHashPrefix("abcdef12...)")
        assertEquals("abcdef12", prefix)
        assertEquals("abcdef123456789hash", VkAuthLogPolicy.resolveGroupHash(7, prefix, listOf("abcdef123456789hash")))
    }

    @Test fun `unknown or ambiguous prefixes are never reported as hashes`() {
        assertNull(VkAuthLogPolicy.resolveGroupHash(7, "unknown1", listOf("abcdef123456789hash")))
        assertNull(VkAuthLogPolicy.resolveGroupHash(7, "abcdef12", listOf("abcdef123456789hash", "abcdef129876543hash")))
    }

    @Test fun `groups without a logged prefix retain the existing slot fallback`() {
        assertEquals("hash-slot-1", VkAuthLogPolicy.resolveGroupHash(4, null, listOf("hash-slot-0", "hash-slot-1")))
    }
}
