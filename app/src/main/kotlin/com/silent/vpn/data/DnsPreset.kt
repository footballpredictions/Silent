package com.silent.vpn.data

/**
 * Пресеты DNS — только debug-сборка (меню «DNS»).
 * Release всегда берёт wg_dns с сервера (Яндекс).
 */
enum class DnsPreset(
    val id: String,
    val title: String,
    val subtitle: String,
    val servers: String,
) {
    YANDEX(
        id = "yandex",
        title = "Яндекс",
        subtitle = "77.88.8.8 · как на сервере",
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
    );

    companion object {
        val DEFAULT = YANDEX

        fun fromId(id: String?): DnsPreset =
            entries.firstOrNull { it.id == id } ?: DEFAULT
    }
}
