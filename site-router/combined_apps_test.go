package main

import (
	"net/netip"
	"testing"
	"time"
)

func TestCombinedRussianModeRetainsExplicitAppAndSameIPIsolation(t *testing.T) {
	ip := netip.MustParseAddr("203.0.113.7")
	p := newProcessPolicy(policyConfig{Excluded: []string{"game.exe"}, Russian: russianConfig{Enabled: true, VPN: []string{"forced.ru"}}})
	p.russian.observe(ruFixture("forced.ru", true, [4]byte{203, 0, 113, 7}))
	if !p.direct("game.exe", ip, 443) {
		t.Fatal("Explicit app exclusion was lost under RU mode")
	}
	if p.direct("other.exe", ip, 443) {
		t.Fatal("Shared-IP app escaped the VPN")
	}
	if p.direct("game.exe", netip.MustParseAddr("10.66.66.1"), 8000) || p.direct("game.exe", ip, 53) {
		t.Fatal("Service API/DNS guard lost")
	}
}

func TestCombinedExclusionEditChangesOnlySelectedLiveFlow(t *testing.T) {
	cfg := policyConfig{Russian: russianConfig{Enabled: true}}
	router := &routedTun{routes: make(map[flow]cachedRoute), fragments: make(map[fragmentKey]cachedRoute), owner: func(f flow) string {
		if f.Local == "10.0.0.2:50000" {
			return "game.exe"
		}
		return "other.exe"
	}}
	router.policy.Store(newProcessPolicy(cfg))
	selected := flow{Protocol: 17, Local: "10.0.0.2:50000", Remote: "203.0.113.7:443"}
	other := flow{Protocol: 17, Local: "10.0.0.2:50001", Remote: selected.Remote}
	router.routes[selected] = cachedRoute{expires: time.Now().Add(time.Hour)}
	router.routes[other] = cachedRoute{expires: time.Now().Add(time.Hour)}
	cfg.Excluded = []string{"game.exe"}
	if changed := router.updatePolicy(cfg); changed != 1 {
		t.Fatalf("changed flows=%d, want 1", changed)
	}
	if _, ok := router.routes[other]; !ok {
		t.Fatal("Unrelated flow was removed")
	}
}

func TestCombinedCachedAppRouteRetainsPriorityOverVPNDomain(t *testing.T) {
	p := newProcessPolicy(policyConfig{Excluded: []string{"game.exe"}, Russian: russianConfig{Enabled: true, VPN: []string{"forced.ru"}}})
	p.russian.observe(ruFixture("forced.ru", true, [4]byte{203, 0, 113, 7}))
	router := &routedTun{routes: make(map[flow]cachedRoute), owner: func(flow) string { return "game.exe" }}
	router.policy.Store(p)
	f := flow{Protocol: 17, Local: "10.0.0.2:50000", Remote: "203.0.113.7:443"}
	packet := make([]byte, 28)
	packet[0] = 0x45
	if !router.choose(f, packet) || !router.choose(f, packet) {
		t.Fatal("Cached explicit app exclusion was overridden by RU VPN rules")
	}
}

func TestUnixPolicyEditUsesOneOwnerSnapshotForManyFlows(t *testing.T) {
	count := 0
	router := &routedTun{routes: make(map[flow]cachedRoute), fragments: make(map[fragmentKey]cachedRoute),
		owner:         func(flow) string { t.Fatal("Per-flow OS owner lookup during policy batch"); return "" },
		ownerSnapshot: func(*processPolicy) func(flow) string { count++; return func(flow) string { return "game.exe" } },
	}
	cfg := policyConfig{Russian: russianConfig{Enabled: true}}
	router.policy.Store(newProcessPolicy(cfg))
	for i := 0; i < 100; i++ {
		f := flow{Protocol: 17, Local: netip.AddrPortFrom(netip.MustParseAddr("10.0.0.2"), uint16(50000+i)).String(), Remote: "203.0.113.7:443"}
		router.routes[f] = cachedRoute{expires: time.Now().Add(time.Hour)}
	}
	cfg.Excluded = []string{"game.exe"}
	if changed := router.updatePolicy(cfg); changed != 100 || count != 1 {
		t.Fatalf("changed=%d snapshots=%d", changed, count)
	}
	f := flow{Protocol: 17, Local: "10.0.0.2:50000", Remote: "203.0.113.7:443"}
	router.routes[f] = cachedRoute{direct: true, appExcluded: true, owner: "game.exe", expires: time.Now().Add(time.Hour)}
	cfg.Russian.Enabled = false
	if changed := router.updatePolicy(cfg); changed != 0 || count != 1 {
		t.Fatalf("RU-only edit queried owners or changed selected app: %d/%d", changed, count)
	}
}
