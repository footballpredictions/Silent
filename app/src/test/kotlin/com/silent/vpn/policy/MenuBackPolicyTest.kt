package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Test

class MenuBackPolicyTest {

    @Test
    fun `back from a submenu returns to the menu list`() {
        assertEquals(
            MenuBackStep.TO_MENU_ROOT,
            MenuBackPolicy.step(debugLogOpen = false, menuOpen = true, onMenuRoot = false),
        )
    }

    @Test
    fun `back from the menu list closes the menu and stays in the app`() {
        assertEquals(
            MenuBackStep.CLOSE_MENU,
            MenuBackPolicy.step(debugLogOpen = false, menuOpen = true, onMenuRoot = true),
        )
    }

    @Test
    fun `back on the main screen leaves the app`() {
        assertEquals(
            MenuBackStep.LEAVE_APP,
            MenuBackPolicy.step(debugLogOpen = false, menuOpen = false, onMenuRoot = true),
        )
    }

    @Test
    fun `debug log closes before the menu`() {
        assertEquals(
            MenuBackStep.CLOSE_DEBUG_LOG,
            MenuBackPolicy.step(debugLogOpen = true, menuOpen = true, onMenuRoot = false),
        )
    }
}
