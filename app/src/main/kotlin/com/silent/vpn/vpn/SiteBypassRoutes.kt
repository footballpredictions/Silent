package com.silent.vpn.vpn

import com.silent.vpn.util.DebugLog
import java.net.InetAddress
import java.net.URI
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap

/**
 * Правила обхода VPN для сайтов: IP / CIDR / wildcard IP / домены.
 * На выходе — список «дыр» (CIDR), которые вычитаются из 0.0.0.0/0 в AllowedIPs.
 *
 * Примеры:
 *   1.2.3.4
 *   10.0.0.0/8
 *   111.222.*.*
 *   ozon.ru
 *   *.ozon.ru
 */
object SiteBypassRoutes {
    private const val TAG = "SiteBypass"
    const val MAX_RULES = 100
    private const val MAX_EXCLUDE_PREFIXES = 400
    private const val MAX_ALLOWED_PREFIXES = 2000
    private const val RESOLVE_TTL_MS = 5 * 60 * 1000L

    private val resolveCache = ConcurrentHashMap<String, Pair<Long, Set<Ipv4Cidr>>>()

    data class BuildResult(
        val allowedIps: String,
        val excludeCidrs: List<String>,
        val excludeCount: Int,
        val unresolved: List<String>,
        val truncated: Boolean,
        val resolvedPreview: List<String> = emptyList(),
    )

    fun parseRules(raw: String): List<String> =
        raw.lineSequence()
            .map { it.substringBefore('#').trim() }
            .map { normalizeRuleInput(it) }
            .filter { it.isNotEmpty() }
            .distinct()
            .toList()

    fun limitRules(rules: List<String>): List<String> = rules.take(MAX_RULES)

    fun normalizeRuleInput(raw: String): String {
        var s = raw.trim()
        if (s.isEmpty()) return s
        if (s.startsWith("http://", ignoreCase = true) || s.startsWith("https://", ignoreCase = true)) {
            s = runCatching { URI(s).host?.trim().orEmpty() }.getOrDefault("")
            if (s.isEmpty()) {
                // fallback без java.net.URI (редкие схемы)
                s = raw.trim()
                    .removePrefix("https://")
                    .removePrefix("http://")
                    .removePrefix("HTTPS://")
                    .removePrefix("HTTP://")
                    .substringBefore('/')
                    .substringBefore('?')
                    .substringBefore('#')
                    .trim()
            }
        } else if ('/' in s && !s.matches(Regex("""^\d+\.\d+\.\d+\.\d+/\d{1,2}$"""))) {
            // path after domain (not CIDR)
            if (!s.substringBefore('/').matches(Regex("""^\d+\.\d+\.\d+\.\d+$"""))) {
                s = s.substringBefore('/').trim()
            }
        }
        return s.trim().trimEnd('.')
    }

    fun clearResolveCache() {
        resolveCache.clear()
    }

    fun hasDomainRules(raw: String): Boolean =
        parseRules(raw).any { parseRule(it) == null && domainLookupHosts(it) != null }

    /**
     * Резолвит правила → список дыр (ip или cidr-строки) для merge с TURN/VK excludes.
     */
    fun resolveExcludeTargets(rawRules: String): BuildResult {
        val rules = limitRules(parseRules(rawRules))
        if (rules.isEmpty()) {
            return BuildResult("0.0.0.0/0", emptyList(), 0, emptyList(), false)
        }

        val excludes = linkedSetOf<Ipv4Cidr>()
        val unresolved = mutableListOf<String>()
        val resolvedPreview = mutableListOf<String>()
        var truncated = false

        for (rule in rules) {
            if (excludes.size >= MAX_EXCLUDE_PREFIXES) {
                truncated = true
                break
            }
            val parsed = parseRule(rule)
            if (parsed != null) {
                excludes.addAll(parsed)
                continue
            }
            val hosts = domainLookupHosts(rule)
            if (hosts == null) {
                unresolved.add(rule)
                continue
            }
            val resolved = resolveHosts(hosts)
            if (resolved.isEmpty()) {
                unresolved.add(rule)
                continue
            }
            excludes.addAll(resolved)
            if (resolvedPreview.size < 4) {
                resolvedPreview.add(
                    "$rule → ${resolved.take(4).joinToString { it.toString() }}",
                )
            }
        }

        val capped = excludes.take(MAX_EXCLUDE_PREFIXES)
        if (excludes.size > capped.size) truncated = true

        var allowed = complementCidrs(capped)
        var appliedExcludes = capped.size
        if (allowed.size > MAX_ALLOWED_PREFIXES) {
            truncated = true
            var lo = 0
            var hi = capped.size
            var best = emptyList<Ipv4Cidr>()
            var bestN = 0
            while (lo <= hi) {
                val mid = (lo + hi) / 2
                val candidate = complementCidrs(capped.take(mid))
                if (candidate.size <= MAX_ALLOWED_PREFIXES) {
                    best = candidate
                    bestN = mid
                    lo = mid + 1
                } else {
                    hi = mid - 1
                }
            }
            allowed = best
            appliedExcludes = bestN
            DebugLog.w(TAG, "AllowedIPs limit: applied $appliedExcludes/${capped.size}")
        }

        if (allowed.isEmpty()) {
            DebugLog.w(TAG, "Bypass excluded entire IPv4; fallback 0.0.0.0/0")
            return BuildResult(
                "0.0.0.0/0",
                capped.take(appliedExcludes).map { it.toString() },
                appliedExcludes,
                unresolved,
                true,
                resolvedPreview,
            )
        }

        DebugLog.i(
            TAG,
            "excludes=${capped.size} applied=$appliedExcludes allowed=${allowed.size} unresolved=${unresolved.size}",
        )
        return BuildResult(
            allowedIps = allowed.joinToString(", ") { it.toString() },
            excludeCidrs = capped.take(appliedExcludes).map { it.toString() },
            excludeCount = appliedExcludes,
            unresolved = unresolved,
            truncated = truncated,
            resolvedPreview = resolvedPreview,
        )
    }

    private fun parseRule(rule: String): List<Ipv4Cidr>? {
        parseCidr(rule)?.let { return listOf(it) }
        parseIpWildcard(rule)?.let { return listOf(it) }
        return null
    }

    private fun domainLookupHosts(rule: String): List<String>? {
        var host = normalizeRuleInput(rule).lowercase(Locale.US)
        if (host.startsWith("*.")) {
            host = host.removePrefix("*.")
            if (!isDomainName(host)) return null
            return listOf(host, "www.$host")
        }
        if (!isDomainName(host)) return null
        return listOf(host)
    }

    private fun isDomainName(host: String): Boolean {
        if (host.length !in 1..253) return false
        if (host.startsWith(".") || host.endsWith(".") || ".." in host) return false
        if (!host.contains('.')) return false
        val labels = host.split('.')
        if (labels.any { it.isEmpty() || it.length > 63 }) return false
        if (labels.any { !it.matches(Regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")) }) return false
        return labels.last().any { it.isLetter() }
    }

    private fun resolveHosts(hosts: List<String>): Set<Ipv4Cidr> {
        val now = System.currentTimeMillis()
        val out = linkedSetOf<Ipv4Cidr>()
        for (host in hosts) {
            val cached = resolveCache[host]
            if (cached != null && now - cached.first < RESOLVE_TTL_MS && cached.second.isNotEmpty()) {
                out.addAll(cached.second)
                continue
            }
            val addrs = runCatching {
                InetAddress.getAllByName(host)
                    .mapNotNull { it.hostAddress?.trim() }
                    .filter { it.matches(Regex("""\d+\.\d+\.\d+\.\d+""")) }
                    .mapNotNull { parseCidr(it) }
                    .toSet()
            }.getOrElse {
                DebugLog.w(TAG, "DNS $host: ${it.message}")
                emptySet()
            }
            val effective = if (addrs.isNotEmpty()) {
                addrs
            } else {
                cached?.second.orEmpty()
            }
            if (effective.isNotEmpty()) {
                resolveCache[host] = now to effective
                out.addAll(effective)
            }
        }
        return out
    }

    private fun parseCidr(raw: String): Ipv4Cidr? {
        val s = raw.trim()
        val slash = s.indexOf('/')
        if (slash < 0) {
            val ip = parseIpv4(s) ?: return null
            return Ipv4Cidr(ip, 32)
        }
        val ip = parseIpv4(s.substring(0, slash)) ?: return null
        val prefix = s.substring(slash + 1).toIntOrNull() ?: return null
        if (prefix !in 0..32) return null
        return Ipv4Cidr(ip, prefix).networkCidr()
    }

    private fun parseIpWildcard(raw: String): Ipv4Cidr? {
        val parts = raw.trim().split('.')
        if (parts.size != 4) return null
        if (parts.none { it == "*" }) return null
        var network = 0L
        var prefix = 0
        var seenStar = false
        for (i in 0..3) {
            val p = parts[i]
            if (p == "*") {
                seenStar = true
                continue
            }
            if (seenStar) return null
            val o = p.toIntOrNull() ?: return null
            if (o !in 0..255) return null
            network = network or (o.toLong() shl (24 - 8 * i))
            prefix = (i + 1) * 8
        }
        return Ipv4Cidr(network, prefix).networkCidr()
    }

    private fun parseIpv4(s: String): Long? {
        val parts = s.split('.')
        if (parts.size != 4) return null
        var ip = 0L
        for (i in 0..3) {
            val o = parts[i].toIntOrNull() ?: return null
            if (o !in 0..255) return null
            ip = ip or (o.toLong() shl (24 - 8 * i))
        }
        return ip
    }

    /** 0.0.0.0/0 минус holes → компактный AllowedIPs. */
    fun complementCidrs(holes: Collection<Ipv4Cidr>): List<Ipv4Cidr> {
        if (holes.isEmpty()) return listOf(Ipv4Cidr.ALL)

        val ranges = holes.map { h ->
            val n = h.networkCidr()
            val start = n.network
            val hostBits = 32 - n.prefixLen
            val size = if (hostBits >= 32) 0x1_0000_0000L else (1L shl hostBits)
            start to (start + size - 1)
        }.sortedBy { it.first }

        val merged = ArrayList<Pair<Long, Long>>(ranges.size)
        for ((start, end) in ranges) {
            if (merged.isEmpty() || start > merged.last().second + 1) {
                merged.add(start to end)
            } else {
                val prev = merged.removeAt(merged.lastIndex)
                merged.add(prev.first to maxOf(prev.second, end))
            }
        }

        val out = ArrayList<Ipv4Cidr>(merged.size * 2 + 2)
        var cursor = 0L
        for ((start, end) in merged) {
            if (cursor < start) {
                out.addAll(rangeToCidrs(cursor, start - 1))
            }
            cursor = end + 1
            if (cursor > 0xFFFF_FFFFL) break
        }
        if (cursor <= 0xFFFF_FFFFL) {
            out.addAll(rangeToCidrs(cursor, 0xFFFF_FFFFL))
        }
        return out
    }

    private fun rangeToCidrs(start: Long, end: Long): List<Ipv4Cidr> {
        if (start > end) return emptyList()
        if (start == 0L && end == 0xFFFF_FFFFL) return listOf(Ipv4Cidr.ALL)

        val out = ArrayList<Ipv4Cidr>(8)
        var cur = start
        while (cur <= end) {
            val remaining = end - cur + 1
            val alignBits = when {
                cur == 0L -> 31
                else -> cur.countTrailingZeroBits().coerceAtMost(31)
            }
            var lenBits = 0
            while (lenBits < alignBits) {
                val nextSize = 1L shl (lenBits + 1)
                if (nextSize > remaining) break
                lenBits++
            }
            val block = 1L shl lenBits
            out.add(Ipv4Cidr(cur, 32 - lenBits))
            cur += block
        }
        return out
    }
}

data class Ipv4Cidr(val network: Long, val prefixLen: Int) {
    init {
        require(prefixLen in 0..32)
        require(network in 0..0xFFFF_FFFFL)
    }

    fun networkCidr(): Ipv4Cidr = Ipv4Cidr(network and mask(), prefixLen)

    fun mask(): Long = if (prefixLen == 0) 0L else (-1L shl (32 - prefixLen)) and 0xFFFF_FFFFL

    override fun toString(): String {
        val a = ((network ushr 24) and 0xff).toInt()
        val b = ((network ushr 16) and 0xff).toInt()
        val c = ((network ushr 8) and 0xff).toInt()
        val d = (network and 0xff).toInt()
        return "$a.$b.$c.$d/$prefixLen"
    }

    companion object {
        val ALL = Ipv4Cidr(0, 0)
    }
}
