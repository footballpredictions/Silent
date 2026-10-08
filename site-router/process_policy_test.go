package main

import (
	"encoding/json"
	"net/netip"
	"testing"
)

func TestStartupBrowserAllowlistDoesNotLeakBeforeDNSSnapshot(t *testing.T) {
	var cfg policyConfig
	if err := json.Unmarshal([]byte(`{"whitelist":true,"domains":["2ip.io"],"pendingDNS":true,"excluded":["msedge.exe"]}`), &cfg); err != nil {
		t.Fatal(err)
	}
	p := newProcessPolicy(cfg)
	ip := netip.MustParseAddr("188.40.167.81")
	if p.direct("chrome.exe", ip, 443) {
		t.Fatal("selected site escaped VPN while startup DNS snapshot was pending")
	}
	if !p.direct("msedge.exe", ip, 443) || p.direct("game.exe", ip, 443) {
		t.Fatal("startup browser readiness changed explicit app routing")
	}
	if err := json.Unmarshal([]byte(`{"whitelist":true,"domains":["2ip.io"],"targets":["188.40.167.81/32"]}`), &cfg); err != nil {
		t.Fatal(err)
	}
	// A full snapshot explicitly ends the pending stage.
	cfgJSON := []byte(`{"whitelist":true,"domains":["2ip.io"],"targets":["188.40.167.81/32"],"pendingDNS":false}`)
	if err := json.Unmarshal(cfgJSON, &cfg); err != nil {
		t.Fatal(err)
	}
	next := updatedProcessPolicy(p, cfg)
	if next.direct("chrome.exe", ip, 443) || !next.direct("chrome.exe", netip.MustParseAddr("9.9.9.9"), 443) {
		t.Fatal("resolved browser snapshot did not activate the allowlist")
	}
}

func TestWindowsBrowserRulesDoNotChangeApplicationRoute(t *testing.T) {
	p := newProcessPolicy(policyConfig{Whitelist: true, Targets: []string{"8.8.8.8/32"}})
	for _, exe := range []string{"C:\\Apps\\game.exe", "C:\\Apps\\Telegram.exe", ""} {
		if p.direct(exe, netip.MustParseAddr("9.9.9.9"), 443) {
			t.Fatalf("application escaped VPN: %q", exe)
		}
	}
	if !p.direct("C:\\Chrome\\chrome.exe", netip.MustParseAddr("9.9.9.9"), 443) {
		t.Fatal("browser outside allowlist must be direct")
	}
	if p.direct("C:\\Chrome\\chrome.exe", netip.MustParseAddr("8.8.8.8"), 443) {
		t.Fatal("selected browser site must use VPN")
	}
}
func TestAppExclusionWinsWithoutAffectingBrowserAtSameIP(t *testing.T) {
	p := newProcessPolicy(policyConfig{Excluded: []string{"C:\\Apps\\game.exe"}, Targets: []string{"9.9.9.9/32"}})
	ip := netip.MustParseAddr("8.8.8.8")
	if !p.direct("C:\\Apps\\game.exe", ip, 443) {
		t.Fatal("excluded app must be direct")
	}
	if p.direct("C:\\Chrome\\chrome.exe", ip, 443) {
		t.Fatal("same IP must remain in VPN for browser")
	}
	if p.direct("C:\\Apps\\game.exe", netip.MustParseAddr("10.66.66.1"), 8000) {
		t.Fatal("API must stay in VPN")
	}
}
func TestBrowserIdentityDoesNotIncludeEmbeddedWebViews(t *testing.T) {
	for _, exe := range []string{"msedgewebview2.exe", "electron.exe", "C:\\Apps\\browser.exe"} {
		if isBrowser(exe) {
			t.Fatal(exe)
		}
	}
	if !isBrowser("C:\\Users\\me\\Yandex\\YandexBrowser\\Application\\browser.exe") {
		t.Fatal("Yandex not recognized")
	}
}

func TestDNSAnswersSurviveAppEditsAndSnapshotRefresh(t *testing.T) {
	cfg := policyConfig{Whitelist: true, Domains: []string{"2ip.io"}}
	p := newProcessPolicy(cfg)
	p.sites.observeDNS(answerPacket(t, "static.2ip.io", [4]byte{188, 114, 97, 3}, 300))
	cfg.Excluded = []string{"game.exe"}
	next := updatedProcessPolicy(p, cfg)
	if next.direct("chrome.exe", netip.MustParseAddr("188.114.97.3"), 443) {
		t.Fatal("app edit lost browser CDN DNS")
	}
	cfg.Domains = nil
	next = updatedProcessPolicy(next, cfg)
	if !next.direct("chrome.exe", netip.MustParseAddr("188.114.97.3"), 443) {
		t.Fatal("deleted domain retained selected DNS address")
	}
}

func TestSiteEditsPreserveDNSOnlyForRemainingDomains(t *testing.T) {
	cfg := policyConfig{Whitelist: true, Domains: []string{"2ip.io", "mail.ru"}}
	p := newProcessPolicy(cfg)
	p.sites.observeDNS(answerPacket(t, "static.2ip.io", [4]byte{188, 114, 97, 3}, 300))
	p.sites.observeDNS(answerPacket(t, "mail.ru", [4]byte{9, 9, 9, 9}, 300))
	cfg.Domains = []string{"2ip.io", "example.com"}
	next := updatedProcessPolicy(p, cfg)
	if next.direct("chrome.exe", netip.MustParseAddr("188.114.97.3"), 443) {
		t.Fatal("editing another domain lost cached CDN address")
	}
	if !next.direct("chrome.exe", netip.MustParseAddr("9.9.9.9"), 443) {
		t.Fatal("deleted domain kept its learned address")
	}
}
