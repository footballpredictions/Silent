// router-dns supplies exact-name routing to dnsmasq without widening names to suffix rules.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/miekg/dns"
	"silent-keenetic/routerpolicy"
)

type adapter struct {
	policyFile       string
	source           net.IP
	upstream, direct []string
	mu               sync.Mutex
	policy           routerpolicy.Policy
	checked          time.Time
	loaded           bool
	learned          map[string]map[string]bool
	sink             func(context.Context, string, []string) error
	slots            chan struct{}
}

func addresses(value string) ([]string, error) {
	var result []string
	for _, item := range strings.Split(value, ",") {
		item = strings.TrimSpace(item)
		if net.ParseIP(item) != nil {
			item = net.JoinHostPort(item, "53")
		}
		host, port, err := net.SplitHostPort(item)
		if err != nil || net.ParseIP(host) == nil || net.ParseIP(host).To4() == nil || port == "" {
			return nil, errors.New("DNS must be IPv4[:port]")
		}
		number, parseErr := strconv.Atoi(port)
		if parseErr != nil || number < 1 || number > 65535 {
			return nil, errors.New("invalid DNS port")
		}
		result = append(result, item)
	}
	if len(result) == 0 || len(result) > 4 {
		return nil, errors.New("one to four DNS servers required")
	}
	return result, nil
}
func (a *adapter) getPolicy() (routerpolicy.Policy, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.loaded && time.Since(a.checked) < 5*time.Second {
		return a.policy, nil
	}
	a.checked = time.Now()
	file, err := os.Open(a.policyFile)
	if err == nil {
		var raw []byte
		raw, err = io.ReadAll(io.LimitReader(file, routerpolicy.MaxSize+1))
		file.Close()
		if err == nil {
			var p routerpolicy.Policy
			p, err = routerpolicy.Parse(raw)
			if err == nil {
				if !a.loaded || p.Revision != a.policy.Revision {
					a.learned = map[string]map[string]bool{}
				}
				a.policy = p
				a.loaded = true
			}
		}
	}
	if a.loaded {
		return a.policy, nil
	} // A malformed refresh never discards the last working policy.
	return a.policy, errors.New("no valid routing policy")
}
func (a *adapter) addIPs(ctx context.Context, set string, ips []string) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.learned == nil {
		a.learned = map[string]map[string]bool{}
	}
	if a.learned[set] == nil {
		a.learned[set] = map[string]bool{}
	}
	var fresh []string
	pending := map[string]bool{}
	for _, ip := range ips {
		parsed := net.ParseIP(ip)
		if parsed == nil || parsed.To4() == nil || !parsed.IsGlobalUnicast() {
			continue
		}
		if !a.learned[set][ip] && !pending[ip] {
			fresh = append(fresh, ip)
			pending[ip] = true
		}
	}
	if len(fresh) == 0 {
		return nil
	}
	if len(a.learned[set])+len(fresh) > 131072 {
		return errors.New("routing address limit")
	}
	if err := a.sink(ctx, set, fresh); err != nil {
		return err
	}
	for _, ip := range fresh {
		a.learned[set][ip] = true
	}
	return nil
}
func nftSink(ctx context.Context, set string, ips []string) error {
	if set != "sv_ru" && set != "sv_ru_vpn" {
		return errors.New("foreign nft set")
	}
	for _, ip := range ips {
		if parsed := net.ParseIP(ip); parsed == nil || parsed.To4() == nil {
			return errors.New("invalid address")
		}
	}
	if len(ips) == 0 {
		return nil
	}
	command := exec.CommandContext(ctx, "nft", "-f", "-")
	command.Stdin = strings.NewReader("add element inet fw4 " + set + " { " + strings.Join(ips, ", ") + " }\n")
	return command.Run()
}
func (a *adapter) exchange(q *dns.Msg, network string, server string, direct bool) (*dns.Msg, error) {
	dialer := &net.Dialer{Timeout: 3 * time.Second}
	if !direct {
		if network == "tcp" {
			dialer.LocalAddr = &net.TCPAddr{IP: a.source}
		} else {
			dialer.LocalAddr = &net.UDPAddr{IP: a.source}
		}
	}
	client := &dns.Client{Net: network, Timeout: 3 * time.Second, Dialer: dialer}
	response, _, err := client.Exchange(q, server)
	return response, err
}
func (a *adapter) ServeDNS(w dns.ResponseWriter, q *dns.Msg) {
	fail := func(code int) { answer := new(dns.Msg); answer.SetRcode(q, code); _ = w.WriteMsg(answer) }
	host, _, err := net.SplitHostPort(w.RemoteAddr().String())
	if err != nil || !net.ParseIP(host).IsLoopback() || len(q.Question) != 1 || q.Question[0].Qclass != dns.ClassINET {
		fail(dns.RcodeRefused)
		return
	}
	select {
	case a.slots <- struct{}{}:
		defer func() { <-a.slots }()
	default:
		fail(dns.RcodeServerFailure)
		return
	}
	if q.Question[0].Qtype == dns.TypeAAAA {
		answer := new(dns.Msg)
		answer.SetReply(q)
		_ = w.WriteMsg(answer)
		return
	}
	policy, err := a.getPolicy()
	if err != nil {
		fail(dns.RcodeServerFailure)
		return
	}
	route := policy.Match(q.Question[0].Name)
	servers := a.upstream
	if route == routerpolicy.Direct {
		servers = a.direct
	}
	var answer *dns.Msg
	for _, server := range servers {
		answer, err = a.exchange(q, "udp", server, route == routerpolicy.Direct)
		if err == nil && answer.Truncated {
			answer, err = a.exchange(q, "tcp", server, route == routerpolicy.Direct)
		}
		if err == nil && answer != nil {
			break
		}
	}
	if err != nil || answer == nil {
		fail(dns.RcodeServerFailure)
		return
	}
	if answer.Rcode == dns.RcodeSuccess && route != routerpolicy.Default {
		var ips []string
		for _, rr := range answer.Answer {
			if record, ok := rr.(*dns.A); ok {
				ips = append(ips, record.A.String())
			}
		}
		set := "sv_ru"
		if route == routerpolicy.VPN {
			set = "sv_ru_vpn"
		}
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		err = a.addIPs(ctx, set, ips)
		cancel()
		if err != nil {
			fail(dns.RcodeServerFailure)
			return
		}
	}
	_ = w.WriteMsg(answer)
}
func (a *adapter) restore(ctx context.Context) {
	ticker := time.NewTicker(20 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_, _ = a.getPolicy()
			a.mu.Lock()
			for set, values := range a.learned {
				ips := make([]string, 0, len(values))
				for ip := range values {
					ips = append(ips, ip)
				}
				timeout, cancel := context.WithTimeout(ctx, 3*time.Second)
				_ = a.sink(timeout, set, ips)
				cancel()
			}
			a.mu.Unlock()
		}
	}
}
func run() error {
	policy := flag.String("policy", "/etc/silent-vpn/routing-policy.json", "validated policy cache")
	source := flag.String("source", "", "WireGuard IPv4 source")
	upstream := flag.String("upstream", "1.1.1.1,1.0.0.1", "VPN DNS servers")
	direct := flag.String("direct-dns", "77.88.8.8,77.88.8.1", "direct DNS servers")
	listen := flag.String("listen", "127.0.0.1:15354", "loopback listener")
	ready := flag.String("ready", "/var/run/silent-vpn/catalog-dns.ready", "readiness marker")
	check := flag.Bool("check", false, "validate inputs without starting")
	flag.Parse()
	host, _, err := net.SplitHostPort(*listen)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		return errors.New("listener must be loopback")
	}
	ip := net.ParseIP(*source)
	if ip == nil || ip.To4() == nil || (!ip.IsPrivate() && !ip.IsLoopback()) {
		return errors.New("WireGuard source IPv4 required")
	}
	a := &adapter{policyFile: *policy, source: ip, sink: nftSink, slots: make(chan struct{}, 64)}
	if a.upstream, err = addresses(*upstream); err != nil {
		return err
	}
	if a.direct, err = addresses(*direct); err != nil {
		return err
	}
	if _, err = a.getPolicy(); err != nil {
		return err
	}
	if *check {
		return nil
	}
	udp, err := net.ListenPacket("udp4", *listen)
	if err != nil {
		return err
	}
	defer udp.Close()
	tcp, err := net.Listen("tcp4", *listen)
	if err != nil {
		return err
	}
	defer tcp.Close()
	servers := []*dns.Server{{Net: "udp", PacketConn: udp, Handler: a}, {Net: "tcp", Listener: tcp, Handler: a, ReadTimeout: 5 * time.Second, WriteTimeout: 5 * time.Second}}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	for _, server := range servers {
		go func(s *dns.Server) {
			if s.ActivateAndServe() != nil {
				stop()
			}
		}(server)
	}
	if err = os.WriteFile(*ready, []byte(fmt.Sprint(os.Getpid())), 0600); err != nil {
		return err
	}
	defer os.Remove(*ready)
	go a.restore(ctx)
	<-ctx.Done()
	for _, server := range servers {
		timeout, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		_ = server.ShutdownContext(timeout)
		cancel()
	}
	return nil
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
