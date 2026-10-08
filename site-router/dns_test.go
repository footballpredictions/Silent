package main

import (
	"encoding/binary"
	"net/netip"
	"testing"
	"time"

	"golang.org/x/net/dns/dnsmessage"
)

func answerPacket(t *testing.T, domain string, address [4]byte, ttl uint32) []byte {
	t.Helper()
	name := dnsmessage.MustNewName(domain + ".")
	message := dnsmessage.Message{
		Header:    dnsmessage.Header{ID: 42, Response: true},
		Questions: []dnsmessage.Question{{Name: name, Type: dnsmessage.TypeA, Class: dnsmessage.ClassINET}},
		Answers:   []dnsmessage.Resource{{Header: dnsmessage.ResourceHeader{Name: name, Type: dnsmessage.TypeA, Class: dnsmessage.ClassINET, TTL: ttl}, Body: &dnsmessage.AResource{A: address}}},
	}
	body, err := message.Pack()
	if err != nil {
		t.Fatal(err)
	}
	packet := make([]byte, 28+len(body))
	packet[0] = 0x45
	packet[9] = 17
	binary.BigEndian.PutUint16(packet[2:4], uint16(len(packet)))
	binary.BigEndian.PutUint16(packet[20:22], 53)
	binary.BigEndian.PutUint16(packet[22:24], 42000)
	binary.BigEndian.PutUint16(packet[24:26], uint16(8+len(body)))
	copy(packet[28:], body)
	return packet
}

func TestBrowserUsesActualVpnDNSForSiteAndItsResources(t *testing.T) {
	// Carrier warm-up DNS returned 172.67.x, but the browser's VPN resolver
	// returned 188.114.x. This is the observed static.2ip.io failure.
	p := newPolicy(true, []string{"172.67.134.103/32"}, []int{10001})
	p.domains = []string{"2ip.io"}
	actual := netip.MustParseAddr("188.114.97.3")
	if !p.direct(10001, actual) {
		t.Fatal("fixture must initially reproduce browser resource bypass")
	}
	p.observeDNS(answerPacket(t, "static.2ip.io", actual.As4(), 60))
	if p.direct(10001, actual) {
		t.Fatal("selected site's resource used direct route after its actual DNS answer")
	}
	if p.direct(10002, actual) || p.direct(-1, actual) {
		t.Fatal("domain learning changed an application or unknown owner's VPN")
	}
}

func TestBypassLearnsMailAddressWithoutChangingApplications(t *testing.T) {
	p := newPolicy(false, nil, []int{10001})
	p.domains = []string{"mail.ru"}
	ip := netip.MustParseAddr("90.156.232.4")
	p.observeDNS(answerPacket(t, "e.mail.ru", ip.As4(), 60))
	if !p.direct(10001, ip) {
		t.Fatal("browser did not apply site bypass to resolved subdomain")
	}
	if p.direct(10002, ip) {
		t.Fatal("mail site's rule bypassed mail application's VPN")
	}
}

func TestDNSLearningRejectsUnrelatedDomainsAndExpires(t *testing.T) {
	p := newPolicy(true, nil, []int{10001})
	p.domains = []string{"2ip.io"}
	ip := netip.MustParseAddr("188.114.97.3")
	p.observeDNS(answerPacket(t, "evil2ip.io", ip.As4(), 60))
	if !p.direct(10001, ip) {
		t.Fatal("partial domain suffix was accepted")
	}
	now := time.Unix(1000, 0)
	p.now = func() time.Time { return now }
	p.observeDNS(answerPacket(t, "static.2ip.io", ip.As4(), 5))
	if p.direct(10001, ip) {
		t.Fatal("valid DNS response ignored")
	}
	now = now.Add(6 * time.Second)
	if !p.direct(10001, ip) {
		t.Fatal("expired DNS mapping retained")
	}
}

func TestMalformedDNSDoesNotChangePolicy(t *testing.T) {
	p := newPolicy(true, nil, []int{10001})
	p.domains = []string{"2ip.io"}
	packet := answerPacket(t, "static.2ip.io", [4]byte{188, 114, 97, 3}, 60)
	for n := 0; n < len(packet); n++ {
		p.observeDNS(packet[:n])
	}
	if !p.direct(10001, netip.MustParseAddr("188.114.97.3")) {
		t.Fatal("truncated packet updated policy")
	}
}
