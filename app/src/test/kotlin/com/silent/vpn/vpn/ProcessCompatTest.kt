package com.silent.vpn.vpn

import com.silent.vpn.util.isAliveCompat
import com.silent.vpn.util.waitForCompat
import com.silent.vpn.util.destroyForciblyCompat
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class ProcessCompatTest {
    private class LegacyProcess(var alive: Boolean = true) : Process() {
        override fun getOutputStream() = ByteArrayOutputStream()
        override fun getInputStream() = ByteArrayInputStream(byteArrayOf())
        override fun getErrorStream() = ByteArrayInputStream(byteArrayOf())
        override fun waitFor(): Int = 0
        override fun exitValue(): Int {
            if (alive) throw IllegalThreadStateException()
            return 0
        }
        override fun destroy() { alive = false }
        override fun isAlive(): Boolean = throw NoSuchMethodError("API26")
        override fun waitFor(timeout: Long, unit: TimeUnit): Boolean = throw NoSuchMethodError("API26")
        override fun destroyForcibly(): Process = throw NoSuchMethodError("API26")
    }

    @Test fun legacyAliveDoesNotCallMissingApi() {
        val p = LegacyProcess()
        assertTrue(p.isAliveCompat())
        p.alive = false
        assertFalse(p.isAliveCompat())
    }

    @Test fun legacyTimedWaitIsBounded() {
        assertFalse(LegacyProcess().waitForCompat(1, TimeUnit.MILLISECONDS))
        assertTrue(LegacyProcess(false).waitForCompat(0, TimeUnit.SECONDS))
    }

    @Test fun legacyDestroyDoesNotCallMissingApi() {
        val p = LegacyProcess()
        p.destroyForciblyCompat()
        assertFalse(p.isAliveCompat())
    }
}
