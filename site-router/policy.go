package main

import (
	"net/netip"
	"sync"
	"time"
)

type sitePolicy struct {
	whitelist    bool
	targets      []netip.Prefix
	browsers     map[int]bool
	domains      []string
	mu           sync.RWMutex
	learned      map[netip.Addr]time.Time
	learnedNames map[netip.Addr]map[string]time.Time
	now          func() time.Time
}

func newPolicy(whitelist bool, targets []string, browsers []int) *sitePolicy {
	p := &sitePolicy{whitelist: whitelist, browsers: make(map[int]bool), learned: make(map[netip.Addr]time.Time), learnedNames: make(map[netip.Addr]map[string]time.Time), now: time.Now}
	for _, uid := range browsers {
		if uid >= 0 {
			p.browsers[uid] = true
		}
	}
	for _, raw := range targets {
		prefix, err := netip.ParsePrefix(raw)
		if err != nil {
			if addr, e := netip.ParseAddr(raw); e == nil {
				prefix = netip.PrefixFrom(addr, addr.BitLen())
				err = nil
			}
		}
		if err == nil {
			p.targets = append(p.targets, prefix.Masked())
		}
	}
	return p
}

func (p *sitePolicy) direct(uid int, destination netip.Addr) bool {
	if !p.browsers[uid] || netip.MustParsePrefix("10.66.66.0/24").Contains(destination) {
		return false
	}
	found := false
	for _, target := range p.targets {
		if target.Contains(destination) {
			found = true
			break
		}
	}
	if !found {
		p.mu.RLock()
		until, exists := p.learned[destination]
		found = exists && p.now().Before(until)
		p.mu.RUnlock()
	}
	if p.whitelist {
		return !found
	}
	return found
}
