package com.silent.vpn.vpn

import java.io.InputStream
import java.io.IOException

/** Reads the native router's lifetime stream on its status thread. */
internal object RouterProcessOutput {
    fun consume(input: InputStream, onLine: (String) -> Unit) {
        try {
            input.bufferedReader().useLines { lines -> lines.forEach(onLine) }
        } catch (_: IOException) {
            // Android closes Process streams from another thread during destroy().
            // The owner decides whether this was a replacement or an unexpected exit.
        }
    }
}
