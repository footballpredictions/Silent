package com.silent.vpn.vpn

import java.io.InputStream
import java.io.InterruptedIOException
import org.junit.Assert.assertEquals
import org.junit.Test

class RouterProcessOutputTest {
    @Test
    fun `replacing router while status reader is blocked does not crash process`() {
        val lines = mutableListOf<String>()
        val input = object : InputStream() {
            private val prefix = "READY\n".toByteArray()
            private var offset = 0
            override fun read(): Int {
                if (offset < prefix.size) return prefix[offset++].toInt()
                throw InterruptedIOException("read interrupted by close() on another thread")
            }
            override fun read(buffer: ByteArray, off: Int, len: Int): Int {
                if (offset >= prefix.size) return read()
                val count = minOf(len, prefix.size - offset)
                prefix.copyInto(buffer, off, offset, offset + count)
                offset += count
                return count
            }
        }
        RouterProcessOutput.consume(input, lines::add)
        assertEquals(listOf("READY"), lines)
    }

    @Test
    fun `ordinary output reaches status handler until EOF`() {
        val lines = mutableListOf<String>()
        RouterProcessOutput.consume("READY\nFLOW owner=browser route=vpn\n".byteInputStream(), lines::add)
        assertEquals(listOf("READY", "FLOW owner=browser route=vpn"), lines)
    }
}
