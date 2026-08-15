package com.silent.vpn.data

import android.content.Context

/**
 * DNS туннеля: «Как на сервере» + свой ввод (меню «DNS»).
 * [SERVER] — ничего не подменяет, DNS приходит с сервера в `wg_dns`
 * (в том числе `10.66.66.1`, когда включён фильтр угроз).
 */
enum class DnsPreset(
    val id: String,
    val title: String,
    val subtitle: String,
    val servers: String,
) {
    SERVER(
        id = "server",
        title = "Как на сервере",
        subtitle = "DNS выдаёт Silent · рекомендуется",
        servers = "",
    ),

    /** Не в меню: запасные адреса, когда сервер не прислал `wg_dns`. */
    YANDEX(
        id = "yandex",
        title = "Яндекс",
        subtitle = "77.88.8.8",
        servers = "77.88.8.8, 77.88.8.1",
    ),
    CUSTOM(
        id = "custom",
        title = "Свой DNS",
        subtitle = "до 3 адресов через запятую",
        servers = "",
    ),
    ;

    companion object {
        val DEFAULT = SERVER

        /** Когда сервер не прислал `wg_dns` и подменять нечем. */
        val FALLBACK = YANDEX

        const val MAX_CUSTOM_SERVERS = 3

        private val IPV4 = Regex(
            """^((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$""",
        )

        /**
         * Публичные пресеты 1.0.161 (`yandex`, `cloudflare`, …) сворачиваем в [SERVER]:
         * принудительный публичный DNS ломал резолв в туннеле.
         */
        fun fromId(id: String?): DnsPreset = if (id == CUSTOM.id) CUSTOM else SERVER

        /** Пресеты для меню: свой ввод показывается отдельной секцией. */
        fun selectable(): List<DnsPreset> = listOf(SERVER)

        /**
         * Нормализует ввод пользователя: адреса через запятую/пробел/перевод строки.
         * Возвращает null, если ни одного корректного адреса нет.
         */
        fun sanitizeCustomServers(raw: String?): String? {
            val tokens = raw.orEmpty()
                .split(',', ';', ' ', '\n', '\r', '\t')
                .map { it.trim() }
                .filter { it.isNotEmpty() }
                .filter { isValidServer(it) }
                .distinct()
                .take(MAX_CUSTOM_SERVERS)
            return tokens.takeIf { it.isNotEmpty() }?.joinToString(", ")
        }

        fun isValidServer(token: String): Boolean =
            IPV4.matches(token) || isIpv6(token)

        private fun isIpv6(token: String): Boolean {
            if (!token.contains(':')) return false
            if (token.count { it == ':' } < 2) return false
            if (token.length > 45) return false
            return token.all { it.isDigit() || it in 'a'..'f' || it in 'A'..'F' || it == ':' || it == '.' }
        }
    }
}

/** Единая точка чтения DNS-настроек: prefs → адреса для туннеля. */
object DnsSettings {
    fun preset(context: Context): DnsPreset = runCatching {
        DnsPreset.fromId(
            SilentPrefs.open(context)
                .getString(SilentRepository.PREF_DNS_PRESET, DnsPreset.DEFAULT.id),
        )
    }.getOrDefault(DnsPreset.DEFAULT)

    fun customRaw(context: Context): String = runCatching {
        SilentPrefs.open(context).getString(SilentRepository.PREF_DNS_CUSTOM, "").orEmpty()
    }.getOrDefault("")

    /** Адреса для подмены DNS; null — оставить то, что прислал сервер. */
    fun override(context: Context): String? = override(preset(context), customRaw(context))

    fun override(preset: DnsPreset, customRaw: String?): String? = when (preset) {
        DnsPreset.SERVER -> null
        DnsPreset.CUSTOM -> DnsPreset.sanitizeCustomServers(customRaw)
        else -> preset.servers
    }

    /** Что показать в меню и в логе VPN. */
    fun describe(preset: DnsPreset, customRaw: String?): String = when (preset) {
        DnsPreset.SERVER -> preset.title
        DnsPreset.CUSTOM -> {
            val servers = DnsPreset.sanitizeCustomServers(customRaw)
            if (servers != null) "Свой: $servers" else "Свой DNS (не задан)"
        }
        else -> "${preset.title} (${preset.servers})"
    }

    fun describe(context: Context): String = describe(preset(context), customRaw(context))

    /** Короткая подпись для пункта меню. */
    fun shortLabel(preset: DnsPreset, customRaw: String?): String = when (preset) {
        DnsPreset.CUSTOM -> DnsPreset.sanitizeCustomServers(customRaw) ?: "не задан"
        else -> preset.title
    }

    /** Адреса без IPv6 — для olcrtc/hev, который умеет только IPv4. */
    fun ipv4Servers(context: Context): List<String> {
        val raw = override(context) ?: DnsPreset.FALLBACK.servers
        return raw.split(',')
            .map { it.trim() }
            .filter { it.isNotBlank() && !it.contains(':') }
            .ifEmpty { DnsPreset.FALLBACK.servers.split(',').map { it.trim() } }
    }
}
