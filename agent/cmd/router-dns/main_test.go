package main

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/miekg/dns"
	"silent-keenetic/routerpolicy"
)

func fixtureDNS(t *testing.T, ip string) (string, *atomic.Int32) {
	t.Helper()
	tcpCount := new(atomic.Int32)
	tcp, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	udp, err := net.ListenPacket("udp4", tcp.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	handler := dns.HandlerFunc(func(w dns.ResponseWriter, q *dns.Msg) {
		r := new(dns.Msg)
		r.SetReply(q)
		if strings.HasPrefix(q.Question[0].Name, "large.") && strings.HasPrefix(w.LocalAddr().Network(), "udp") {
			r.Truncated = true
		} else {
			if strings.HasPrefix(w.LocalAddr().Network(), "tcp") {
				tcpCount.Add(1)
			}
			r.Answer = []dns.RR{&dns.A{Hdr: dns.RR_Header{Name: q.Question[0].Name, Rrtype: dns.TypeA, Class: dns.ClassINET, Ttl: 60}, A: net.ParseIP(ip)}}
		}
		_ = w.WriteMsg(r)
	})
	servers := []*dns.Server{{Net: "udp", PacketConn: udp, Handler: handler}, {Net: "tcp", Listener: tcp, Handler: handler}}
	for _, server := range servers {
		go server.ActivateAndServe()
	}
	t.Cleanup(func() {
		for _, s := range servers {
			_ = s.Shutdown()
		}
		udp.Close()
		tcp.Close()
	})
	return tcp.Addr().String(), tcpCount
}
func fixtureAdapter(t *testing.T) (*adapter, string, *[]string, *sync.Mutex, *atomic.Int32) {
	t.Helper()
	direct, tcp := fixtureDNS(t, "192.0.2.1")
	tunnel, _ := fixtureDNS(t, "198.51.100.1")
	p := routerpolicy.Policy{Schema: 1, Revision: strings.Repeat("a", 64), Profile: routerpolicy.Catalog, Direct: []string{"service.ru"}, Exact: []string{"exact.test", "large.exact.test", "special.force.ru"}, VPN: []string{"force.ru", "vpn.service.ru"}}
	raw, _ := json.Marshal(p)
	path := filepath.Join(t.TempDir(), "policy.json")
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	writes := new([]string)
	mu := new(sync.Mutex)
	a := &adapter{policyFile: path, source: net.ParseIP("127.0.0.1"), upstream: []string{tunnel}, direct: []string{direct}, slots: make(chan struct{}, 64), sink: func(_ context.Context, set string, ips []string) error {
		mu.Lock()
		defer mu.Unlock()
		*writes = append(*writes, set+":"+strings.Join(ips, ","))
		return nil
	}}
	udp, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	front := &dns.Server{Net: "udp", PacketConn: udp, Handler: a}
	go front.ActivateAndServe()
	t.Cleanup(func() { _ = front.Shutdown(); udp.Close() })
	return a, udp.LocalAddr().String(), writes, mu, tcp
}
func lookup(t *testing.T, server, name string) *dns.Msg {
	t.Helper()
	q := new(dns.Msg)
	q.SetQuestion(name, dns.TypeA)
	r, _, err := (&dns.Client{Timeout: 3 * time.Second}).Exchange(q, server)
	if err != nil {
		t.Fatal(err)
	}
	return r
}
func TestActualDNSExactSuffixVPNAndTCPFallback(t *testing.T) {
	_, server, writes, mu, tcp := fixtureAdapter(t)
	for name, want := range map[string]string{"exact.test.": "192.0.2.1", "child.exact.test.": "198.51.100.1", "child.service.ru.": "192.0.2.1", "vpn.service.ru.": "198.51.100.1", "special.force.ru.": "198.51.100.1", "large.exact.test.": "192.0.2.1"} {
		r := lookup(t, server, name)
		if r.Rcode != dns.RcodeSuccess || len(r.Answer) != 1 || r.Answer[0].(*dns.A).A.String() != want {
			t.Fatalf("%s: %v", name, r)
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if len(*writes) != 2 {
		t.Fatalf("sets must be deduplicated, direct and forced-VPN kept separate: %v", *writes)
	}
	if tcp.Load() == 0 {
		t.Fatal("truncated DNS did not retry over TCP")
	}
}
func TestKernelRoutingFailureDoesNotReturnUnroutedAddress(t *testing.T) {
	a, server, _, _, _ := fixtureAdapter(t)
	a.sink = func(context.Context, string, []string) error { return errors.New("nft unavailable") }
	r := lookup(t, server, "exact.test.")
	if r.Rcode != dns.RcodeServerFailure || len(r.Answer) != 0 {
		t.Fatal("unrouted address leaked", r)
	}
}
func TestMalformedRefreshKeepsLastGoodPolicy(t *testing.T) {
	a, server, _, _, _ := fixtureAdapter(t)
	_ = lookup(t, server, "exact.test.")
	if err := os.WriteFile(a.policyFile, []byte(`{"direct_domains":true}`), 0600); err != nil {
		t.Fatal(err)
	}
	a.mu.Lock()
	a.checked = time.Time{}
	a.mu.Unlock()
	r := lookup(t, server, "exact.test.")
	if r.Rcode != dns.RcodeSuccess || r.Answer[0].(*dns.A).A.String() != "192.0.2.1" {
		t.Fatal("lost last-good policy")
	}
}
func TestNftAdapterRejectsForeignResourcesAndInvalidInput(t *testing.T) {
	for _, tt := range []struct {
		set string
		ips []string
	}{{"foreign", []string{"192.0.2.1"}}, {"sv_ru", []string{"1.1.1.1;flush ruleset"}}, {"sv_ru_vpn", []string{"::1"}}} {
		if nftSink(context.Background(), tt.set, tt.ips) == nil {
			t.Fatal("accepted invalid nft operation")
		}
	}
}
