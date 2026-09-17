package com.silent.vpn.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class EmailConfirmationPolicyTest {

    @Test
    fun defaultShowsCheckEmailScreen() {
        assertFalse(EmailConfirmationPolicy.skipConfirmation(themeSkip = false, requiredFlag = null))
        assertFalse(EmailConfirmationPolicy.skipConfirmation(themeSkip = false, requiredFlag = "true"))
        assertFalse(EmailConfirmationPolicy.skipConfirmation(themeSkip = false, requiredFlag = ""))
    }

    @Test
    fun themeToggleSkipsCheckEmail() {
        assertTrue(EmailConfirmationPolicy.skipConfirmation(themeSkip = true, requiredFlag = null))
        assertTrue(EmailConfirmationPolicy.skipConfirmation(themeSkip = true, requiredFlag = "true"))
    }

    @Test
    fun registerFlagFalseSkipsCheckEmail() {
        assertTrue(EmailConfirmationPolicy.skipConfirmation(themeSkip = false, requiredFlag = "false"))
        assertTrue(EmailConfirmationPolicy.skipConfirmation(themeSkip = false, requiredFlag = "FALSE"))
    }
}
