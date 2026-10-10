package main

import (
	"context"
	"fmt"
	"net"
	"strings"
	"time"

	"github.com/miekg/dns"
)

type dnsServer struct{ server *dns.Server }

func suffixMatch(name string, domains []string) bool {
	name = strings.TrimSuffix(strings.ToLower(name), ".")
	for _, d := range domains {
		if name == d || strings.HasSuffix(name, "."+d) {
			return true
		}
	}
	return false
}

func (a *Agent) answerDNS(w dns.ResponseWriter, q *dns.Msg) {
	_, subnet, _ := net.ParseCIDR(a.cfg.LANPrefix)
	addr, _, _ := net.SplitHostPort(w.RemoteAddr().String())
	if !subnet.Contains(net.ParseIP(addr)) || len(q.Question) != 1 {
		r := new(dns.Msg)
		r.SetRcode(q, dns.RcodeRefused)
		_ = w.WriteMsg(r)
		return
	}
	// IPv6 is blocked for VPN LAN forwarding too. No AAAA leaks around IPv4 WG.
	if q.Question[0].Qtype == dns.TypeAAAA {
		r := new(dns.Msg)
		r.SetReply(q)
		_ = w.WriteMsg(r)
		return
	}
	a.mu.RLock()
	direct := a.cfg.Direct && suffixMatch(q.Question[0].Name, a.domains)
	upstream := append([]string(nil), a.upstream...)
	wgIP := a.wgAddress
	a.mu.RUnlock()
	c := &dns.Client{Timeout: 3 * time.Second, Dialer: boundDialer(wgIP, false)}
	if direct {
		c.Dialer = &net.Dialer{Timeout: 3 * time.Second}
		upstream = []string{"77.88.8.8", "77.88.8.1"}
	}
	var answer *dns.Msg
	for _, ip := range upstream {
		r, _, err := c.Exchange(q, net.JoinHostPort(ip, "53"))
		if err == nil && r.Truncated {
			c.Net = "tcp"
			if !direct {
				c.Dialer = boundDialer(wgIP, true)
			}
			r, _, err = c.Exchange(q, net.JoinHostPort(ip, "53"))
			c.Net = ""
			if !direct {
				c.Dialer = boundDialer(wgIP, false)
			}
		}
		if err == nil && r != nil {
			answer = r
			break
		}
	}
	if answer == nil {
		answer = new(dns.Msg)
		answer.SetRcode(q, dns.RcodeServerFailure)
	}
	if direct && answer.Rcode == dns.RcodeSuccess {
		for _, rr := range answer.Answer {
			if ar, ok := rr.(*dns.A); ok {
				ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
				err := a.run(ctx, "ipset", "add", "svk_direct", ar.A.String(), "-exist")
				cancel()
				if err != nil {
					answer = new(dns.Msg)
					answer.SetRcode(q, dns.RcodeServerFailure)
					break
				}
			}
		}
	}
	_ = w.WriteMsg(answer)
}

func (a *Agent) startDNS() error {
	address := net.JoinHostPort(a.cfg.LANIP, "15353")
	udp, err := net.ListenPacket("udp4", address)
	if err != nil {
		return fmt.Errorf("DNS UDP: %w", err)
	}
	tcp, err := net.Listen("tcp4", address)
	if err != nil {
		udp.Close()
		return fmt.Errorf("DNS TCP: %w", err)
	}
	for _, s := range []*dns.Server{{PacketConn: udp, Net: "udp", Handler: dns.HandlerFunc(a.answerDNS)}, {Listener: tcp, Net: "tcp", Handler: dns.HandlerFunc(a.answerDNS), ReadTimeout: 5 * time.Second, WriteTimeout: 5 * time.Second}} {
		a.servers = append(a.servers, &dnsServer{s})
		go func(s *dns.Server) { _ = s.ActivateAndServe() }(s)
	}
	return nil
}
func (a *Agent) stopDNS() {
	for _, s := range a.servers {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		_ = s.server.ShutdownContext(ctx)
		cancel()
	}
	a.servers = nil
}
