package com.silent.vpn.vk

object VkBootstrap {
    const val PREFIX = "SILENT:boot:"

    fun extract(text: String): String? {
        val idx = text.indexOf(PREFIX)
        if (idx < 0) return null
        val rest = text.substring(idx + PREFIX.length)
        val end = rest.indexOfFirst { it.isWhitespace() }
        val hash = if (end < 0) rest.trim() else rest.substring(0, end).trim()
        return hash.takeIf { it.length >= 8 }
    }
}
