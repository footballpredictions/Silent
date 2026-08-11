package com.silent.vpn.data

import android.content.Context

/**
 * DNS туннеля: пресеты + свой ввод (меню «DNS»).
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
    YANDEX(
        id = "yandex",
        title = "Яндекс",
        subtitle = "77.88.8.8",
        servers = "77.88.8.8, 77.88.8.1",
    ),
    CLOUDFLARE(
        id = "cloudflare",
        title = "Cloudflare",
        subtitle = "1.1.1.1",
        servers = "1.1.1.1, 1.0.0.1",
    ),
    GOOGLE(
        id = "google",
        title = "Google",
        subtitle = "8.8.8.8",
        servers = "8.8.8.8, 8.8.4.4",
    ),
    QUAD9(
        id = "quad9",
        title = "Quad9",
        subtitle = "9.9.9.9",
        servers = "9.9.9.9, 149.112.112.112",
    ),
    OPENDNS(
        id = "opendns",
        title = "OpenDNS",
        subtitle = "208.67.222.222",
        servers = "208.67.222.222, 208.67.220.220",
    ),
    ADGUARD(
        id = "adguard",
        title = "AdGuard DNS",
        subtitle = "94.140.14.14",
        servers = "94.140.14.14, 94.140.15.15",
    ),
    CLEANBROWSING(
        id = "cleanbrowsing",
        title = "CleanBrowsing",
        subtitle = "185.228.168.9",
        servers = "185.228.168.9, 185.228.169.9",
    ),
    COMODO(
        id = "comodo",
        title = "Comodo Secure DNS",
        subtitle = "8.26.56.26",
        servers = "8.26.56.26, 8.20.247.20",
    ),
    VERISIGN(
        id = "verisign",
        title = "Verisign",
        subtitle = "64.6.64.6",
        servers = "64.6.64.6, 64.6.65.6",
    ),
    LEVEL3(
        id = "level3",
        title = "Level3",
        subtitle = "4.2.2.1",
        servers = "4.2.2.1, 4.2.2.2",
    ),
    UNCENSORED(
        id = "uncensoreddns",
        title = "UncensoredDNS",
        subtitle = "91.239.100.100",
        servers = "91.239.100.100, 89.233.43.71",
    ),
    ALTERNATE(
        id = "alternate",
        title = "Alternate DNS",
        subtitle = "76.76.19.19",
        servers = "76.76.19.19, 76.223.122.150",
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

        fun fromId(id: String?): DnsPreset =
            entries.firstOrNull { it.id == id } ?: DEFAULT

        /** Пресеты для меню: свой ввод показывается отдельной секцией. */
        fun selectable(): List<DnsPreset> = entries.filter { it != CUSTOM }

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
