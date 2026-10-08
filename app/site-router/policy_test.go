package main

import (
	"net/netip"
	"testing"
)

// Both flows have the SAME destination. A global AllowedIPs whitelist cannot
// implement this: only the browser flow may bypass; the app must keep its VPN.
func TestBrowserRulesDoNotChangeApplicationRoute(t *testing.T) {
	p := newPolicy(true, []string{"203.0.113.1/32"}, []int{10001})
	destination := netip.MustParseAddr("198.51.100.1")
	if !p.direct(10001, destination) {
		t.Fatal("unlisted browser site should be direct")
	}
	if p.direct(10002, destination) {
		t.Fatal("site whitelist stole application's VPN")
	}
	if p.direct(-1, destination) {
		t.Fatal("unknown owner must keep VPN")
	}
}

func TestSiteBypassOnlyAffectsBrowser(t *testing.T) {
	p := newPolicy(false, []string{"203.0.113.0/24"}, []int{10001})
	listed := netip.MustParseAddr("203.0.113.8")
	if !p.direct(10001, listed) {
		t.Fatal("listed browser site should bypass")
	}
	if p.direct(10002, listed) {
		t.Fatal("listed site changed application's route")
	}
	if p.direct(10001, netip.MustParseAddr("198.51.100.1")) {
		t.Fatal("other browser site should keep VPN")
	}
}

func TestServiceAddressesAlwaysKeepVpn(t *testing.T) {
	p := newPolicy(true, nil, []int{10001})
	if p.direct(10001, netip.MustParseAddr("10.66.66.1")) {
		t.Fatal("VPN API must stay reachable")
	}
}
