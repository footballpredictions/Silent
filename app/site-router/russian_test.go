package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"golang.org/x/net/dns/dnsmessage"
	"net"
	"net/netip"
	"strings"
	"testing"
	"time"
)

func TestCatalogExactRulesDoNotIncludeSubdomains(t *testing.T) {
	config := russianConfig{Enabled: true, DirectExact: []string{"exact.ru"}, Direct: []string{"suffix.ru"}, VPN: []string{"blocked.suffix.ru"}}
	for name, expected := range map[string]bool{"EXACT.RU.": true, "sub.exact.ru": false, "suffix.ru": true, "sub.suffix.ru": true, "unknown.ru": false} {
		if config.matchesDirect(name) != expected {
			t.Fatalf("unexpected exact/suffix match for %s", name)
		}
	}
	router := newRussianRouter(config)
	ip := netip.MustParseAddr("203.0.113.9")
	router.observe(ruFixture("exact.ru", true, ip.As4()))
	if !router.direct(ip) {
		t.Fatal("exact host was not learned as DIRECT")
	}
	epoch := router.epoch()
	config.DirectExact = []string{"other.ru"}
	router.update(config)
	if router.epoch() == epoch || router.direct(ip) {
		t.Fatal("exact rule update did not invalidate learned route")
	}
	router.observe(ruFixture("sub.exact.ru", true, ip.As4()))
	if router.direct(ip) {
		t.Fatal("exact rule leaked into a subdomain")
	}
	router.observe(ruFixture("sub.suffix.ru", true, ip.As4()))
	router.observe(ruFixture("blocked.suffix.ru", true, ip.As4()))
	if router.direct(ip) || !router.mustVPN(ip) {
		t.Fatal("VPN override lost priority on a shared IP")
	}
	if router.handleDNS(context.Background(), ruFixture("blocked.suffix.ru", false, [4]byte{}), func([]byte) error { return nil }) {
		t.Fatal("VPN override query escaped to physical DNS")
	}
}

func TestPhysicalDNSUpdateReachesLookupBeforeNetworkAck(t *testing.T) {
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"flashscore.com"}})
	first := ""
	r.dial = func(ctx context.Context, _, target string) (net.Conn, error) {
		first = target
		client, server := net.Pipe()
		go func() {
			defer server.Close()
			server.Read(make([]byte, 512))
			server.Write(ruFixture("flashscore.com", true, [4]byte{203, 0, 113, 9})[28:])
		}()
		return client, nil
	}
	var output bytes.Buffer
	err := applyRouterUpdates(strings.NewReader("{\"revision\":1,\"network_epoch\":1,\"physical_dns\":[\"192.0.2.53\"]}\n"), newPolicy(false, nil, nil), &output, r, func() {
		if _, err := r.lookup(context.Background(), ruFixture("flashscore.com", false, [4]byte{})[28:]); err != nil {
			t.Error(err)
		}
	})
	if err != nil || first != "192.0.2.53:53" || output.String() != "POLICY_READY:1\n" {
		t.Fatalf("Carrier DNS did not reach the new physical path: first=%s err=%v", first, err)
	}
}

func TestRussianDNSTimeoutReturnsFailureInsteadOfSilence(t *testing.T) {
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"flashscore.com"}})
	r.exchange = func(ctx context.Context, _ []byte) ([]byte, error) { <-ctx.Done(); return nil, ctx.Err() }
	replies := make(chan []byte, 1)
	r.handleDNS(context.Background(), ruFixture("flashscore.com", false, [4]byte{}), func(p []byte) error { replies <- p; return nil })
	select {
	case reply := <-replies:
		answer, _, ok := russianDNS(reply, true)
		if !ok || answer.RCode != dnsmessage.RCodeServerFailure {
			t.Fatal("Expected explicit DNS failure")
		}
	case <-time.After(13 * time.Second):
		t.Fatal("DNS timeout was swallowed; application keeps waiting for a reply")
	}
}

func TestRussianDNSBusyQueueReturnsFailureInsteadOfSilence(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"flashscore.com"}})
	r.exchange = func(ctx context.Context, _ []byte) ([]byte, error) { <-ctx.Done(); return nil, ctx.Err() }
	replies := make(chan []byte, 1)
	for i := 0; i < 33; i++ {
		r.handleDNS(ctx, ruFixture("flashscore.com", false, [4]byte{}), func(p []byte) error { replies <- p; return nil })
	}
	select {
	case reply := <-replies:
		answer, _, ok := russianDNS(reply, true)
		if !ok || answer.RCode != dnsmessage.RCodeServerFailure {
			t.Fatal("Expected retryable DNS busy response")
		}
	case <-time.After(250 * time.Millisecond):
		t.Fatal("Full DNS queue silently swallowed the application request")
	}
}

func TestRussianDNSReadStopsWithLostPhysicalNetwork(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"ru"}})
	started := make(chan struct{}, 1)
	r.dial = func(ctx context.Context, _, _ string) (net.Conn, error) {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		client, server := net.Pipe()
		go func() {
			defer server.Close()
			server.Read(make([]byte, 512))
			started <- struct{}{}
			server.Read(make([]byte, 1))
		}()
		return client, nil
	}
	done := make(chan struct{})
	go func() { r.lookup(ctx, []byte("query")); close(done) }()
	<-started
	cancel()
	select {
	case <-done:
	case <-time.After(250 * time.Millisecond):
		t.Fatal("DNS read retained a socket from the lost network")
	}
}

func TestRussianDNSAcceptsDelayedMobileReply(t *testing.T) {
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"flashscore.com"}})
	ip := [4]byte{203, 0, 113, 9}
	r.dial = func(ctx context.Context, _, _ string) (net.Conn, error) {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		client, server := net.Pipe()
		go func() {
			defer server.Close()
			if _, err := server.Read(make([]byte, 512)); err != nil {
				return
			}
			timer := time.NewTimer(1800 * time.Millisecond)
			defer timer.Stop()
			select {
			case <-timer.C:
				server.Write(ruFixture("flashscore.com", true, ip)[28:])
			case <-ctx.Done():
			}
		}()
		return client, nil
	}
	replies := make(chan []byte, 1)
	r.handleDNS(context.Background(), ruFixture("flashscore.com", false, ip), func(p []byte) error { replies <- p; return nil })
	select {
	case reply := <-replies:
		answer, _, ok := russianDNS(reply, true)
		if !ok || answer.RCode != dnsmessage.RCodeSuccess || !r.direct(netip.AddrFrom4(ip)) {
			t.Fatal("A valid delayed mobile DNS reply was discarded; DIRECT application cannot start")
		}
	case <-time.After(6 * time.Second):
		t.Fatal("Mobile DNS was silently dropped")
	}
}

func ruFixture(name string, response bool, ip [4]byte) []byte {
	q := dnsmessage.Question{Name: dnsmessage.MustNewName(name + "."), Type: dnsmessage.TypeA, Class: dnsmessage.ClassINET}
	msg := dnsmessage.Message{Header: dnsmessage.Header{ID: 17, Response: response}, Questions: []dnsmessage.Question{q}}
	if response {
		msg.Answers = []dnsmessage.Resource{{Header: dnsmessage.ResourceHeader{Name: q.Name, Type: dnsmessage.TypeA, Class: dnsmessage.ClassINET, TTL: 300}, Body: &dnsmessage.AResource{A: ip}}}
	}
	data, _ := msg.Pack()
	packet := make([]byte, 28+len(data))
	packet[0] = 0x45
	packet[9] = 17
	copy(packet[12:16], []byte{10, 66, 66, 2})
	copy(packet[16:20], []byte{1, 1, 1, 1})
	binary.BigEndian.PutUint16(packet[2:4], uint16(len(packet)))
	binary.BigEndian.PutUint16(packet[20:22], 53000)
	binary.BigEndian.PutUint16(packet[22:24], 53)
	binary.BigEndian.PutUint16(packet[24:26], uint16(8+len(data)))
	copy(packet[28:], data)
	if response {
		return russianReply(packet, 20, data)
	}
	return packet
}
func TestRussianModeIsGlobalAndVPNOverrideWinsSharedIP(t *testing.T) {
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"ru", "vk.com"}, VPN: []string{"protected.ru"}})
	ip := [4]byte{203, 0, 113, 2}
	r.observe(ruFixture("video.vk.com", true, ip))
	if !r.direct(netip.AddrFrom4(ip)) {
		t.Fatal("Russian application destination did not bypass VPN")
	}
	if r.direct(netip.MustParseAddr("198.51.100.1")) {
		t.Fatal("Unknown destination left VPN")
	}
	r.observe(ruFixture("protected.ru", true, ip))
	if r.direct(netip.AddrFrom4(ip)) {
		t.Fatal("VPN override lost to a shared Russian CDN address")
	}
}
func TestRussianToggleRetainsLearnedDNSWhileDisablingRouting(t *testing.T) {
	c := russianConfig{Direct: []string{"ru"}}
	r := newRussianRouter(c)
	ip := [4]byte{203, 0, 113, 3}
	r.observe(ruFixture("shop.ru", true, ip))
	if r.direct(netip.AddrFrom4(ip)) {
		t.Fatal("Disabled mode changed routing")
	}
	c.Enabled = true
	r.update(c)
	if !r.direct(netip.AddrFrom4(ip)) {
		t.Fatal("Mode change lost DNS cache")
	}
	c.Enabled = false
	r.update(c)
	if r.direct(netip.AddrFrom4(ip)) {
		t.Fatal("Mode stayed active after turning it off")
	}
}
func TestRussianDNSUsesWANAndLearnsBeforeReply(t *testing.T) {
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"ru"}, VPN: []string{"protected.ru"}})
	ip := [4]byte{203, 0, 113, 4}
	r.exchange = func(_ context.Context, query []byte) ([]byte, error) { return ruFixture("shop.ru", true, ip)[28:], nil }
	replies := make(chan []byte, 1)
	write := func(packet []byte) error {
		if !r.direct(netip.AddrFrom4(ip)) {
			t.Error("DNS answer was delivered before installing its route")
		}
		replies <- packet
		return nil
	}
	if !r.handleDNS(context.Background(), ruFixture("shop.ru", false, ip), write) {
		t.Fatal("Russian DNS was sent through WG")
	}
	select {
	case packet := <-replies:
		if _, _, ok := russianDNS(packet, true); !ok {
			t.Fatal("Invalid DNS reply")
		}
	case <-time.After(time.Second):
		t.Fatal("No DNS reply")
	}
	if r.handleDNS(context.Background(), ruFixture("protected.ru", false, ip), write) {
		t.Fatal("Protected DNS bypassed VPN")
	}
	if r.handleDNS(context.Background(), ruFixture("example.com", false, ip), write) {
		t.Fatal("Foreign DNS bypassed VPN")
	}
}

func TestRussianPolicyUpdateKeepsAnswersAndProtectsServiceNetwork(t *testing.T) {
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"ru"}})
	ip := [4]byte{203, 0, 113, 5}
	r.observe(ruFixture("protected.ru", true, ip))
	r.update(russianConfig{Enabled: true, Direct: []string{"ru"}, VPN: []string{"protected.ru"}})
	if r.direct(netip.AddrFrom4(ip)) {
		t.Fatal("Updated VPN override was ignored")
	}
	r.update(russianConfig{Enabled: true, Direct: []string{"ru"}})
	if !r.direct(netip.AddrFrom4(ip)) {
		t.Fatal("Policy refresh lost a live DNS answer")
	}
	r.observe(ruFixture("internal.ru", true, [4]byte{10, 66, 66, 1}))
	if r.direct(netip.MustParseAddr("10.66.66.1")) {
		t.Fatal("Service API left WG")
	}
	if russianDomain("notru", []string{"ru"}) || russianDomain("ru.example.com", []string{"ru"}) {
		t.Fatal("Invalid suffix match")
	}
}

func TestRussianIPv6AndHTTPSHintsFallBackToIPv4(t *testing.T) {
	r := newRussianRouter(russianConfig{Enabled: true, Direct: []string{"ru"}})
	r.exchange = func(context.Context, []byte) ([]byte, error) {
		t.Error("Address hints went to a resolver")
		return nil, nil
	}
	for _, kind := range []dnsmessage.Type{dnsmessage.TypeAAAA, 64, 65} {
		packet := ruFixture("shop.ru", false, [4]byte{})
		msg, _, _ := russianDNS(packet, false)
		msg.Questions[0].Type = kind
		data, _ := msg.Pack()
		copy(packet[28:], data)
		replies := 0
		if !r.handleDNS(context.Background(), packet, func(reply []byte) error {
			answer, _, ok := russianDNS(reply, true)
			if !ok || answer.RCode != dnsmessage.RCodeSuccess || len(answer.Answers) != 0 {
				t.Error("Invalid empty address-hint reply")
			}
			replies++
			return nil
		}) || replies != 1 {
			t.Fatal("IPv4 fallback was not returned")
		}
	}
}
