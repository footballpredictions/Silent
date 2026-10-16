//go:build linux || android

package main

import (
	"bytes"
	"io"
	"net/netip"
	"os"
	"testing"
	"time"
)

func TestWireGuardDNSReplyUpdatesBrowserPolicyBeforeDelivery(t *testing.T) {
	p := newPolicy(true, []string{"172.67.134.103/32"}, []int{10001})
	p.domains = []string{"2ip.io"}
	reader, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	defer writer.Close()
	adapter := &routedTun{file: writer, policy: p}
	packet := answerPacket(t, "static.2ip.io", [4]byte{188, 114, 97, 3}, 60)
	buffer := append(make([]byte, 16), packet...)
	if n, err := adapter.Write([][]byte{buffer}, 16); n != 1 || err != nil {
		t.Fatalf("reply write: %d %v", n, err)
	}
	if p.direct(10001, netip.MustParseAddr("188.114.97.3")) {
		t.Fatal("browser would bypass the selected site's CDN after receiving its DNS answer")
	}
	delivered := make([]byte, len(packet))
	if _, err := io.ReadFull(reader, delivered); err != nil || !bytes.Equal(delivered, packet) {
		t.Fatal("DNS learning changed the response packet")
	}
	if p.direct(10002, netip.MustParseAddr("188.114.97.3")) {
		t.Fatal("DNS observation changed non-browser routing")
	}
}

func TestRussianModeRoutesAllAppsWithoutOwnerLookup(t *testing.T) {
	russian := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"ru"}})
	russian.observe(ruFixture("shop.ru", true, [4]byte{203, 0, 113, 9}))
	adapter := &routedTun{russian: russian, policy: newPolicy(true, nil, []int{10001}), routes: make(map[flow]cachedRoute)}
	// No control socket: a UID lookup here would panic. The mode is global.
	packet := make([]byte, 40)
	packet[0] = 0x45
	packet[33] = 2
	if !adapter.choose(flow{6, "10.66.66.2:50000", "203.0.113.9:443"}, packet) {
		t.Fatal("RU app stayed in VPN")
	}
	if adapter.choose(flow{6, "10.66.66.2:50001", "198.51.100.9:443"}, packet) {
		t.Fatal("Manual allowlist leaked foreign app")
	}
}

func TestRussianActiveFlowSurvivesDNSExpiryButHonorsRemovedRule(t *testing.T) {
	cfg := russianConfig{Enabled: true, Direct: []string{"ru"}}
	r := newRussianRouter(cfg)
	ip := [4]byte{203, 0, 113, 9}
	r.observe(ruFixture("shop.ru", true, ip))
	adapter := &routedTun{russian: r, policy: newPolicy(false, nil, nil), routes: make(map[flow]cachedRoute)}
	f := flow{6, "10.66.66.2:50000", "203.0.113.9:443"}
	packet := make([]byte, 40)
	packet[0] = 0x45
	packet[33] = 2
	if !adapter.choose(f, packet) {
		t.Fatal("initial route missing")
	}
	packet[33] = 16
	r.mu.Lock()
	r.answers[netip.AddrFrom4(ip)].direct = time.Now().Add(-time.Second)
	r.mu.Unlock()
	if !adapter.choose(f, packet) {
		t.Fatal("DNS TTL broke an active stream")
	}
	r.update(russianConfig{Enabled: true})
	if adapter.choose(f, packet) {
		t.Fatal("Removed DIRECT rule remained active")
	}
}
