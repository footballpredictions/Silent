package main

import (
	"encoding/binary"
	"net/netip"
	"strings"
	"time"

	"golang.org/x/net/dns/dnsmessage"
)

// Actual resolver answers can differ from the physical network's warm-up cache.
// Observe them before delivering them to the browser so its first connection is
// routed with the same addresses it just received.
func (p *sitePolicy) observeDNS(packet []byte) {
	if len(p.domains) == 0 || len(packet) < 28 || packet[0]>>4 != 4 || packet[9] != 17 {
		return
	}
	h := int(packet[0]&15) * 4
	total := int(binary.BigEndian.Uint16(packet[2:4]))
	if h < 20 || h+8 > len(packet) || total > len(packet) || total < h+8 || binary.BigEndian.Uint16(packet[6:8])&0x3fff != 0 {
		return
	}
	udp := packet[h:total]
	size := int(binary.BigEndian.Uint16(udp[4:6]))
	if binary.BigEndian.Uint16(udp[:2]) != 53 || size < 8 || size > len(udp) {
		return
	}
	var parser dnsmessage.Parser
	header, err := parser.Start(udp[8:size])
	if err != nil || !header.Response || header.Truncated || header.OpCode != 0 || header.RCode != dnsmessage.RCodeSuccess {
		return
	}
	questions, err := parser.AllQuestions()
	if err != nil || len(questions) != 1 || questions[0].Class != dnsmessage.ClassINET || !p.matchesDomain(questions[0].Name.String()) {
		return
	}
	answers, err := parser.AllAnswers()
	if err != nil {
		return
	}
	now := p.now()
	p.mu.Lock()
	defer p.mu.Unlock()
	if len(p.learned) >= 4096 {
		for ip, until := range p.learned {
			if !now.Before(until) {
				delete(p.learned, ip)
			}
		}
	}
	for _, answer := range answers {
		a, ok := answer.Body.(*dnsmessage.AResource)
		if !ok || answer.Header.Class != dnsmessage.ClassINET {
			continue
		}
		ip := netip.AddrFrom4(a.A)
		if _, exists := p.learned[ip]; !exists && len(p.learned) >= 4096 {
			continue
		}
		ttl := min(max(time.Duration(answer.Header.TTL)*time.Second, time.Second), 5*time.Minute)
		until := now.Add(ttl)
		if previous := p.learned[ip]; previous.Before(until) {
			p.learned[ip] = until
		}
	}
}

func (p *sitePolicy) matchesDomain(domain string) bool {
	domain = strings.TrimSuffix(strings.ToLower(domain), ".")
	for _, rule := range p.domains {
		rule = strings.TrimSuffix(strings.TrimPrefix(strings.ToLower(rule), "*."), ".")
		if rule != "" && (domain == rule || strings.HasSuffix(domain, "."+rule)) {
			return true
		}
	}
	return false
}
