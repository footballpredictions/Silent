package main

import (
	"context"
	"encoding/binary"
	"errors"
	"golang.org/x/net/dns/dnsmessage"
	"net"
	"net/netip"
	"slices"
	"strings"
	"sync"
	"time"
)

// Same contract on Android, Windows and the iOS packet engine. Manual app/site
// exclusions are deliberately outside this mode. Unknown destinations keep WG.
type russianConfig struct {
	Enabled     bool     `json:"enabled"`
	Direct      []string `json:"direct_domains"`
	DirectExact []string `json:"direct_exact_domains"`
	VPN         []string `json:"vpn_domains"`
}

var russianServiceNetwork = netip.MustParsePrefix("10.66.66.0/24")

type russianAnswer struct {
	names       map[string]time.Time
	direct, vpn time.Time
}
type russianRouter struct {
	mu         sync.RWMutex
	config     russianConfig
	generation uint64
	answers    map[netip.Addr]*russianAnswer
	resolvers  []string
	slots      chan struct{}
	dial       func(context.Context, string, string) (net.Conn, error)
	exchange   func(context.Context, []byte) ([]byte, error)
}

func newRussianRouter(c russianConfig) *russianRouter {
	r := &russianRouter{answers: make(map[netip.Addr]*russianAnswer), slots: make(chan struct{}, 32)}
	r.dial = (&net.Dialer{Timeout: 1500 * time.Millisecond}).DialContext
	r.exchange = r.lookup
	r.updateDNS(nil)
	r.update(c)
	return r
}

// Prefer the current carrier/Wi-Fi DNS. Public resolvers remain fallbacks;
// using only one provider fails on networks that filter third-party UDP DNS.
func (r *russianRouter) updateDNS(addresses []string) {
	servers := make([]string, 0, 6)
	for _, raw := range addresses {
		address, err := netip.ParseAddr(raw)
		if err != nil || address.IsUnspecified() || address.IsMulticast() || address.IsLoopback() {
			continue
		}
		server := net.JoinHostPort(address.String(), "53")
		if !slices.Contains(servers, server) {
			servers = append(servers, server)
		}
		if len(servers) == 4 {
			break
		}
	}
	for _, fallback := range []string{"77.88.8.8:53", "77.88.8.1:53"} {
		if !slices.Contains(servers, fallback) {
			servers = append(servers, fallback)
		}
	}
	r.mu.Lock()
	r.resolvers = servers
	r.mu.Unlock()
}
func russianDomain(name string, rules []string) bool {
	name = strings.TrimSuffix(strings.ToLower(name), ".")
	for _, rule := range rules {
		if name == rule || strings.HasSuffix(name, "."+rule) {
			return true
		}
	}
	return false
}
func (c russianConfig) matchesDirect(name string) bool {
	name = strings.TrimSuffix(strings.ToLower(name), ".")
	return slices.Contains(c.DirectExact, name) || russianDomain(name, c.Direct)
}
func (r *russianRouter) update(c russianConfig) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.config.Enabled != c.Enabled || !slices.Equal(r.config.Direct, c.Direct) || !slices.Equal(r.config.DirectExact, c.DirectExact) || !slices.Equal(r.config.VPN, c.VPN) {
		r.generation++
	}
	r.config = c
	now := time.Now()
	for ip, answer := range r.answers {
		answer.direct, answer.vpn = time.Time{}, time.Time{}
		for name, until := range answer.names {
			if !now.Before(until) {
				delete(answer.names, name)
				continue
			}
			if russianDomain(name, c.VPN) {
				if until.After(answer.vpn) {
					answer.vpn = until
				}
			} else if c.matchesDirect(name) && until.After(answer.direct) {
				answer.direct = until
			}
		}
		if len(answer.names) == 0 {
			delete(r.answers, ip)
		}
	}
}
func (r *russianRouter) epoch() uint64 {
	if r == nil {
		return 0
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.generation
}
func (r *russianRouter) enabled() bool {
	if r == nil {
		return false
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.config.Enabled
}
func (r *russianRouter) mustVPN(ip netip.Addr) bool {
	if russianServiceNetwork.Contains(ip) {
		return true
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	answer := r.answers[ip]
	return answer != nil && time.Now().Before(answer.vpn)
}
func (r *russianRouter) direct(ip netip.Addr) bool {
	if r == nil || !ip.Is4() || russianServiceNetwork.Contains(ip) {
		return false
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	if !r.config.Enabled {
		return false
	}
	a := r.answers[ip]
	now := time.Now()
	return a != nil && !now.Before(a.vpn) && now.Before(a.direct)
}

// Only ordinary, complete IPv4 DNS datagrams are interpreted. Other traffic,
// including DoH/DoT, fragments and unknown owners, retains the normal VPN path.
func russianDNS(packet []byte, response bool) (dnsmessage.Message, int, bool) {
	var message dnsmessage.Message
	if len(packet) < 28 || packet[0]>>4 != 4 || packet[9] != 17 {
		return message, 0, false
	}
	h := int(packet[0]&15) * 4
	size := int(binary.BigEndian.Uint16(packet[2:4]))
	if h < 20 || size > len(packet) || size < h+8 || binary.BigEndian.Uint16(packet[6:8])&0x3fff != 0 {
		return message, 0, false
	}
	udp := packet[h:size]
	port := binary.BigEndian.Uint16(udp[2:4])
	if response {
		port = binary.BigEndian.Uint16(udp[:2])
	}
	length := int(binary.BigEndian.Uint16(udp[4:6]))
	if port != 53 || length < 8 || length > len(udp) {
		return message, 0, false
	}
	if message.Unpack(udp[8:length]) != nil || message.Response != response || message.OpCode != 0 ||
		len(message.Questions) != 1 || message.Questions[0].Class != dnsmessage.ClassINET {
		return message, 0, false
	}
	return message, h, true
}
func (r *russianRouter) observe(packet []byte) {
	if r == nil {
		return
	}
	message, _, ok := russianDNS(packet, true)
	if !ok || message.Truncated || message.RCode != dnsmessage.RCodeSuccess {
		return
	}
	name := strings.TrimSuffix(strings.ToLower(message.Questions[0].Name.String()), ".")
	r.mu.Lock()
	defer r.mu.Unlock()
	vpn := russianDomain(name, r.config.VPN)
	if !vpn && !r.config.matchesDirect(name) {
		return
	}
	now := time.Now()
	for _, answer := range message.Answers {
		body, ok := answer.Body.(*dnsmessage.AResource)
		if !ok || answer.Header.Class != dnsmessage.ClassINET {
			continue
		}
		ip := netip.AddrFrom4(body.A)
		if r.answers[ip] == nil {
			if len(r.answers) >= 8192 {
				for old, a := range r.answers {
					if !now.Before(a.direct) && !now.Before(a.vpn) {
						delete(r.answers, old)
					}
				}
				if len(r.answers) >= 8192 {
					continue
				}
			}
			r.answers[ip] = &russianAnswer{names: make(map[string]time.Time)}
		}
		a := r.answers[ip]
		for old, until := range a.names {
			if !now.Before(until) {
				delete(a.names, old)
			}
		}
		if len(a.names) >= 32 {
			if _, exists := a.names[name]; !exists {
				if !vpn {
					continue
				}
				// A busy shared CDN must never crowd a VPN override out.
				var oldest string
				var expiry time.Time
				for old, until := range a.names {
					if oldest == "" || until.Before(expiry) {
						oldest, expiry = old, until
					}
				}
				delete(a.names, oldest)
			}
		}
		until := now.Add(min(max(time.Duration(answer.Header.TTL)*time.Second, time.Second), 24*time.Hour))
		a.names[name] = until
		if vpn {
			if until.After(a.vpn) {
				a.vpn = until
			}
		} else if until.After(a.direct) {
			a.direct = until
		}
	}
}
func (r *russianRouter) lookup(ctx context.Context, query []byte) ([]byte, error) {
	r.mu.RLock()
	servers := slices.Clone(r.resolvers)
	r.mu.RUnlock()
	for _, server := range servers {
		if ctx.Err() != nil {
			break
		}
		connection, err := r.dial(ctx, "udp", server)
		if err != nil {
			continue
		}
		deadline := time.Now().Add(4 * time.Second)
		if limit, ok := ctx.Deadline(); ok && limit.Before(deadline) {
			deadline = limit
		}
		connection.SetDeadline(deadline)
		stopClose := context.AfterFunc(ctx, func() { connection.Close() })
		_, err = connection.Write(query)
		data := make([]byte, 65507)
		n := 0
		if err == nil {
			n, err = connection.Read(data)
		}
		connection.Close()
		stopClose()
		if err == nil {
			return data[:n], nil
		}
	}
	return nil, errors.New("physical DNS unavailable")
}
func russianReply(query []byte, h int, payload []byte) []byte {
	out := make([]byte, h+8+len(payload))
	copy(out, query[:h+8])
	copy(out[h+8:], payload)
	copy(out[12:16], query[16:20])
	copy(out[16:20], query[12:16])
	copy(out[h:h+2], query[h+2:h+4])
	copy(out[h+2:h+4], query[h:h+2])
	out[8] = 64
	out[10] = 0
	out[11] = 0
	out[h+6] = 0
	out[h+7] = 0
	binary.BigEndian.PutUint16(out[2:4], uint16(len(out)))
	binary.BigEndian.PutUint16(out[h+4:h+6], uint16(8+len(payload)))
	sum := uint32(0)
	for i := 0; i < h; i += 2 {
		sum += uint32(binary.BigEndian.Uint16(out[i : i+2]))
	}
	for sum>>16 != 0 {
		sum = (sum & 0xffff) + (sum >> 16)
	}
	binary.BigEndian.PutUint16(out[10:12], ^uint16(sum))
	return out
}
func (r *russianRouter) handleDNS(ctx context.Context, packet []byte, write func([]byte) error) bool {
	if r == nil {
		return false
	}
	message, h, ok := russianDNS(packet, false)
	if !ok {
		return false
	}
	name := message.Questions[0].Name.String()
	r.mu.RLock()
	direct := r.config.Enabled && r.config.matchesDirect(name) && !russianDomain(name, r.config.VPN)
	r.mu.RUnlock()
	if !direct {
		return false
	}
	// DIRECT currently transports IPv4. Suppress IPv6 and HTTPS/SVCB address
	// hints for these names so clients request an A record before connecting.
	// VPN overrides keep the original resolver and all its record types.
	if message.Questions[0].Type == dnsmessage.TypeAAAA || message.Questions[0].Type == 64 || message.Questions[0].Type == 65 {
		message.Response = true
		message.RecursionAvailable = true
		answer, _ := message.Pack()
		_ = write(russianReply(packet, h, answer))
		return true
	}
	if ctx == nil {
		ctx = context.Background()
	}
	select {
	case r.slots <- struct{}{}:
	default:
		message.Response = true
		message.RCode = dnsmessage.RCodeServerFailure
		answer, _ := message.Pack()
		_ = write(russianReply(packet, h, answer))
		return true
	}
	packet = append([]byte(nil), packet...)
	networkContext := ctx
	go func() {
		defer func() { <-r.slots }()
		ctx, cancel := context.WithTimeout(networkContext, 12*time.Second)
		defer cancel()
		query, _ := message.Pack()
		answer, err := r.exchange(ctx, query)
		var parsed dnsmessage.Message
		if err != nil || parsed.Unpack(answer) != nil || !parsed.Response || parsed.ID != message.ID ||
			len(parsed.Questions) != 1 || parsed.Questions[0] != message.Questions[0] {
			message.Response = true
			message.RCode = dnsmessage.RCodeServerFailure
			answer, _ = message.Pack()
		}
		reply := russianReply(packet, h, answer)
		// A request timeout needs SERVFAIL so the application can retry. Only a
		// retired physical network/session suppresses delivery of this old reply.
		if networkContext.Err() != nil {
			return
		}
		r.observe(reply) // Install the route before the first application TCP/UDP packet.
		_ = write(reply)
	}()
	return true
}
