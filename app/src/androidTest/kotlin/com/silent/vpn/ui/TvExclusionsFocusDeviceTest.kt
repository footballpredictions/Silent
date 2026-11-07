package com.silent.vpn.ui

import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.test.assertIsFocused
import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.performKeyInput
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.pressKey
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.graphics.toPixelMap
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.data.RussianServices
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.ThemeData
import com.silent.vpn.ui.screens.AppExclusionsScreen
import com.silent.vpn.ui.theme.AppearanceMode
import com.silent.vpn.ui.theme.resolveThemePalette
import com.silent.vpn.util.DevicePlatform
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Actual screen and D-pad, with no VPN or account on the disposable emulator. */
@RunWith(AndroidJUnit4::class)
class TvExclusionsFocusDeviceTest {
    @get:Rule val compose = createComposeRule()

    @OptIn(ExperimentalTestApi::class)
    @Test fun dpadReachesRussianServicesAndDrawsBlueRing() {
        assumeTrue(Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val cached = DevicePlatform::class.java.getDeclaredField("cachedIsTv").apply { isAccessible = true }
        val previous = cached.get(DevicePlatform)
        val oldRussian = RussianServices.enabled(context)
        try {
            cached.set(DevicePlatform, true)
            RussianServices.setEnabled(context, false)
            val palette = (null as ThemeData?).resolveThemePalette(AppearanceMode.DARK)
            compose.setContent {
                MaterialTheme {
                    Box(Modifier.fillMaxSize().background(palette.bg)) {
                        AppExclusionsScreen(SilentRepository(context), palette) {}
                    }
                }
            }
            // Let the screen's existing delayed initial focus finish before D-pad input.
            compose.mainClock.advanceTimeBy(160)
            compose.waitForIdle()
            compose.onNodeWithText("← Назад").assertIsFocused()
            compose.onRoot().performKeyInput { pressKey(Key.DirectionDown) }
            val russian = compose.onNodeWithText("Российские сервисы мимо VPN")
            russian.assertIsFocused()
            assertBlueRing(russian)
            InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_DPAD_CENTER)
            compose.waitForIdle()
            compose.runOnIdle { assertTrue(RussianServices.enabled(context)) }
            russian.performSemanticsAction(SemanticsActions.RequestFocus) { it() }
            russian.assertIsFocused()
            assertBlueRing(russian)
            InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_DPAD_CENTER)
            compose.waitForIdle()
            compose.runOnIdle { assertFalse(RussianServices.enabled(context)) }
            compose.onRoot().performKeyInput { pressKey(Key.DirectionUp) }
            compose.onNodeWithText("← Назад").assertIsFocused()
            val search = compose.onNode(hasSetTextAction())
            search.performSemanticsAction(SemanticsActions.RequestFocus) { it() }
            search.assertIsFocused()
            assertBlueRing(search)
            compose.onNodeWithText("← Назад").performSemanticsAction(SemanticsActions.RequestFocus) { it() }
            compose.onRoot().performKeyInput { pressKey(Key.DirectionDown); pressKey(Key.DirectionDown) }
            compose.onNodeWithText("Сайты").assertIsFocused()
            InstrumentationRegistry.getInstrumentation().sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_DPAD_CENTER)
            compose.waitForIdle()
            val domain = compose.onNode(hasSetTextAction())
            domain.performSemanticsAction(SemanticsActions.RequestFocus) { it() }
            domain.assertIsFocused()
            assertBlueRing(domain)
        } finally {
            RussianServices.setEnabled(context, oldRussian)
            cached.set(DevicePlatform, previous)
        }
    }

    private fun assertBlueRing(node: SemanticsNodeInteraction) {
        compose.mainClock.advanceTimeBy(64)
        compose.waitForIdle()
        val pixels = node.captureToImage().toPixelMap()
        var blue = 0
        for (y in 0 until pixels.height) for (x in 0 until pixels.width) {
            val c = pixels[x, y]
            if (c.blue > .7f && c.red < .25f && c.green in .25f.. .55f) blue++
        }
        assertTrue("Focused control must draw its blue TV ring", blue > 30)
    }
}
