package main

import (
	"context"
	"encoding/binary"
	"golang.org/x/net/dns/dnsmessage"
	"net/netip"
	"testing"
	"time"
)

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
