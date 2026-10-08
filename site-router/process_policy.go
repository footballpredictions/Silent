package main

import (
	"net/netip"
	"strings"
	"time"
)

// Browser rules apply to actual browser processes, never to their shared IPs.
// Application exclusions take precedence, as on Android's VpnService.
type processPolicy struct {
	sites    *sitePolicy
	excluded []string
	dns      []string
}

func newProcessPolicy(c policyConfig) *processPolicy {
	p := newPolicy(c.Whitelist, c.Targets, []int{1})
	p.domains = c.Domains
	return &processPolicy{sites: p, excluded: c.Excluded, dns: c.DNS}
}

func updatedProcessPolicy(old *processPolicy, c policyConfig) *processPolicy {
	next := newProcessPolicy(c)
	// Windows/browser DNS caches outlive policy edits. Keep answers associated
	// with remaining rules, including their CDN/subdomain addresses.
	if old != nil {
		old.sites.mu.RLock()
		now := old.sites.now()
		for ip, names := range old.sites.learnedNames {
			for name, until := range names {
				if !now.Before(until) || !next.sites.matchesDomain(name) {
					continue
				}
				if next.sites.learnedNames[ip] == nil {
					next.sites.learnedNames[ip] = make(map[string]time.Time)
				}
				next.sites.learnedNames[ip][name] = until
				if next.sites.learned[ip].Before(until) {
					next.sites.learned[ip] = until
				}
			}
		}
		old.sites.mu.RUnlock()
	}
	return next
}

type policyConfig struct {
	Whitelist bool     `json:"whitelist"`
	Targets   []string `json:"targets"`
	Domains   []string `json:"domains"`
	Excluded  []string `json:"excluded"`
	DNS       []string `json:"dns"`
}

func normalizedExe(s string) string { return strings.ToLower(strings.ReplaceAll(s, "/", "\\")) }
func exeLeaf(s string) string       { s = normalizedExe(s); return s[strings.LastIndex(s, "\\")+1:] }

func isBrowser(exe string) bool {
	switch exeLeaf(exe) {
	case "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "waterfox.exe", "librewolf.exe", "floorp.exe", "zen.exe":
		return true
	case "browser.exe":
		return strings.Contains(normalizedExe(exe), "\\yandex\\")
	}
	return false
}

func (p *processPolicy) appExcluded(exe string) bool {
	if exe == "" {
		return false
	}
	n := normalizedExe(exe)
	for _, e := range p.excluded {
		if normalizedExe(e) == n || exeLeaf(e) == exeLeaf(exe) {
			return true
		}
	}
	return false
}

func (p *processPolicy) direct(exe string, dst netip.Addr, port uint16) bool {
	// Preserve in-tunnel API and configured resolvers, including Windows' DNS client.
	if netip.MustParsePrefix("10.66.66.0/24").Contains(dst) || port == 53 {
		return false
	}
	for _, raw := range p.dns {
		if raw == dst.String() {
			return false
		}
	}
	if exe == "" {
		return false
	}
	if p.appExcluded(exe) {
		return true
	}
	if !isBrowser(exe) {
		return false
	}
	return p.sites.direct(1, dst)
}
